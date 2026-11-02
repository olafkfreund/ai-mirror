"""What happened on the desktop between calls (#95): Hyprland's socket2 lines,
kept in memory while this server's agent holds control, and only then."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from collections import deque

from . import control, host, privacy

CAP = 300
SIZE = 512
# event -> (fields in its data, index of the class, index of the title)
TITLED = {'activewindow': (2, 0, 1), 'openwindow': (4, 2, 3)}

RUNNING = False
CONNECTED = False  # an empty list from a reader that cannot connect would read as "nothing happened"


def parse(line: str) -> tuple[str, str] | None:
    name, sep, data = line.rstrip('\r\n').partition('>>')
    # Not capped here: a private-browsing marker sits at the end of a long title,
    # so redact sees the whole line and add() caps what is stored.
    return (name, data) if sep else None


def _addr(a: str) -> str:
    return a[2:] if a.startswith('0x') else a


def redact(name: str, data: str, classes: dict) -> str:
    """Withhold the title of a private window; titles contain commas, hence maxsplit."""
    if name == 'windowtitlev2':
        addr, _, title = data.partition(',')
        found = privacy.kind(classes.get(_addr(addr), ''), title)
        return f'{addr},<withheld: {found}>' if found else data
    if name not in TITLED:
        return data
    n, ci, ti = TITLED[name]
    parts = data.split(',', n - 1)
    if len(parts) < n:
        return data
    found = privacy.kind(parts[ci], parts[ti])
    if found:
        parts[ti] = f'<withheld: {found}>'
    return ','.join(parts)


def held(state: dict) -> bool:
    # SERVER None is not a holder: a CLI grant also has held_by None.
    return (control.SERVER is not None and state.get('owner') == 'agent'
            and state.get('held_by') == control.SERVER)


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.ring: deque = deque(maxlen=SIZE)
        self.seq = 0
        self.generation = None  # None = not recording
        self.classes: dict = {}
        self.base = 0  # seq when this grant's recording started
        self.closed: set = set()  # layer namespaces seen closing this grant; not in the ring, so overflow cannot lose one

    def add(self, name: str, data: str) -> None:
        with self.lock:
            self.seq += 1
            self.ring.append({'seq': self.seq, 'ms': int(time.time() * 1000),
                              'event': name, 'data': data[:CAP]})

    def gap(self, reason: str) -> None:
        self.add('gap', reason)

    def cursor(self) -> int:
        return self.seq

    def clear(self, generation) -> None:
        with self.lock:
            self.ring.clear()
            self.classes = {}
            self.closed = set()
            self.generation = generation
            self.base = self.seq

    def closed_layers(self, generation) -> set:
        with self.lock:
            return set(self.closed) if generation is not None and generation == self.generation else set()

    def since(self, cursor: int, limit: int) -> dict:
        with self.lock:
            # A cursor from before this grant means "from its start", not a loss;
            # one past seq is from another server life, so it cannot be trusted.
            start = max(cursor, self.base)
            oldest = self.ring[0]['seq'] if self.ring else self.seq + 1
            got = [dict(e) for e in self.ring if e['seq'] > start][:limit]
            return {'events': got, 'next': got[-1]['seq'] if got else self.seq,
                    'dropped': cursor > self.seq or start < oldest - 1}


def seed() -> dict:
    # hyprctl directly, not host.windows(): its retry calls host.resolve(), whose
    # on_switch stops HELPER and writes state from this thread.
    try:
        out = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=2).stdout
        return {_addr(w['address']): w.get('class', '') for w in json.loads(out)}
    except Exception:
        return {}


def feed(line: str, state: dict, recorder: 'Recorder | None' = None) -> None:
    rec = recorder or RECORDER
    if not held(state):
        if rec.generation is not None:
            rec.clear(None)
        return
    if state.get('generation') != rec.generation:
        rec.clear(state.get('generation'))
        rec.classes = seed()
    parsed = parse(line)
    if not parsed:
        return
    name, data = parsed
    if name == 'openwindow':
        parts = data.split(',', 3)
        if len(parts) == 4:
            rec.classes[_addr(parts[0])] = parts[2]
    elif name == 'closewindow':
        rec.classes.pop(_addr(data), None)
    elif name == 'closelayer':
        with rec.lock:
            rec.closed.add(data)
    rec.add(name, redact(name, data, rec.classes))


RECORDER = Recorder()


def _path() -> str:
    runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'  # as control does
    return f'{runtime}/hypr/{os.environ.get(host.SIG, "")}/.socket2.sock'


def pump(sock, recorder: Recorder) -> None:
    """Feed lines until EOF. The timeout lets a revoked grant clear the ring while idle."""
    sock.settimeout(1)
    buf = b''
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            state = control._load()
            if not held(state) and recorder.generation is not None:
                recorder.clear(None)
            continue
        if not chunk:
            return
        buf += chunk
        *lines, buf = buf.split(b'\n')
        for line in lines:
            feed(line.decode('utf-8', 'replace'), control._load(), recorder)


def _connect():
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.connect(_path())
    except BaseException:
        sock.close()
        raise
    return sock


def _session(recorder: Recorder, connect=_connect) -> None:
    global CONNECTED
    sock = connect()
    CONNECTED = True
    try:
        pump(sock, recorder)
    finally:
        CONNECTED = False
        sock.close()
        if recorder.generation is not None:
            recorder.gap('Hyprland event socket lost')


def _loop() -> None:
    while True:
        try:
            _session(RECORDER)
        except Exception:
            pass
        # No host.resolve() here: its on_switch stops HELPER and writes state, which
        # belongs to the main thread. A restart revokes the grant, and the main
        # thread's next hyprctl call repoints the environment this reads.
        time.sleep(1)


def start() -> None:
    global RUNNING
    if RUNNING:
        return
    RUNNING = True
    threading.Thread(target=_loop, daemon=True, name='ai-mirror-events').start()
