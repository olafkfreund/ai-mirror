"""What happened on the desktop between calls (#95): Hyprland's socket2 lines,
kept in memory while this server's agent holds control, and only then."""
from __future__ import annotations

import threading
import time
from collections import deque

from . import control, host, privacy

CAP = 300
SIZE = 512
# event -> (fields in its data, index of the class, index of the title)
TITLED = {'activewindow': (2, 0, 1), 'openwindow': (4, 2, 3)}

RUNNING = False


def parse(line: str) -> tuple[str, str] | None:
    name, sep, data = line.rstrip('\r\n').partition('>>')
    return (name, data[:CAP]) if sep else None


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
            self.generation = generation

    def since(self, cursor: int, limit: int) -> dict:
        with self.lock:
            oldest = self.ring[0]['seq'] if self.ring else self.seq + 1
            got = [dict(e) for e in self.ring if e['seq'] > cursor][:limit]
            return {'events': got, 'next': got[-1]['seq'] if got else self.seq,
                    'dropped': cursor < oldest - 1}


def seed() -> dict:
    try:
        return {_addr(w['address']): w.get('class', '') for w in host.windows()}
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
    rec.add(name, redact(name, data, rec.classes))


RECORDER = Recorder()
