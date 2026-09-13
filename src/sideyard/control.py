"""Host control state, the persistent input helper, and screen capture.

One state file decides whether an agent may drive the desktop. Every change
bumps `generation`, so input observed under an older grant is refused. The
kill switch is a separate process: it writes the state and signals every
registered MCP server, which closes its helper so the helper releases all
held keys and buttons (a virtual keyboard can only be released by its owner).
"""
from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import host

REPO_HELPER = Path(__file__).resolve().parents[2] / 'build/aw_input/aw-input'


class AwError(Exception):
    """Structured error with a stable machine-readable code."""

    def __init__(self, code: str, detail: str = ''):
        self.code = code
        super().__init__(code if not detail else f'{code}: {detail}')


def root() -> Path:
    base = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    path = Path(base) / 'sideyard'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, obj: object) -> None:
    """Write via tmp file + rename so readers (and the bar's FileView) never see partials."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, indent=1, sort_keys=True)
            fh.write('\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def locked(name: str):
    with open(root() / f'{name}.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def proc_start(pid: int) -> str | None:
    """Process birth time; guards pid files against pid reuse."""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (OSError, IndexError):
        return None


# -- control state -----------------------------------------------------------

def read_state() -> dict:
    try:
        state = json.loads((root() / 'state.json').read_text())
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {'owner': 'off', 'generation': 0}


def set_owner(mode: str, by: str) -> dict:
    if mode not in ('agent', 'off') or by not in ('agent', 'human'):
        raise ValueError('mode must be agent or off')
    with locked('control'):
        state = read_state()
        state = {'owner': mode, 'generation': int(state.get('generation', 0)) + 1,
                 'since': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                 'enabled_by': by if mode == 'agent' else None}
        atomic_write_json(root() / 'state.json', state)
    if mode == 'off':
        signal_servers()
    return state


def require_agent(generation: int) -> dict:
    state = read_state()
    if state.get('owner') != 'agent':
        raise AwError('not_owner', 'agent control is off; call control with mode agent')
    if generation != state.get('generation'):
        raise AwError('stale_generation', f"have {state.get('generation')}, want {generation}; observe again")
    return state


# -- MCP server registry for the kill switch ---------------------------------

def servers_dir() -> Path:
    path = root() / 'mcp.d'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def register_server() -> None:
    pid = os.getpid()
    atomic_write_json(servers_dir() / f'{pid}.json', {'pid': pid, 'start': proc_start(pid)})


def unregister_server() -> None:
    (servers_dir() / f'{os.getpid()}.json').unlink(missing_ok=True)


def signal_servers() -> list[int]:
    signalled = []
    for record in servers_dir().glob('*.json'):
        try:
            data = json.loads(record.read_text())
            pid = int(data['pid'])
            if data.get('start') and data['start'] == proc_start(pid):
                os.kill(pid, signal.SIGUSR1)
                signalled.append(pid)
                continue
        except (OSError, ValueError, KeyError, TypeError):
            pass
        record.unlink(missing_ok=True)  # stale
    return signalled


# -- persistent input helper -------------------------------------------------

def helper_binary() -> str:
    found = os.environ.get('SIDEYARD_HELPER') or shutil.which('aw-input')
    if found:
        return found
    if REPO_HELPER.is_file():
        return str(REPO_HELPER)
    raise AwError('unavailable', 'aw-input helper not found (install the flake package or build src/aw_input)')


class Helper:
    """One aw-input process. Closing its stdin makes it release everything and exit."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.origin = (0, 0)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.running:
            return
        box = host.layout_box()
        self.origin = box[:2]
        env = dict(os.environ, AW_EXTENT_W=str(box[2]), AW_EXTENT_H=str(box[3]))
        proc = subprocess.Popen([helper_binary()], env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1, close_fds=True)
        ready, _, _ = select.select([proc.stdout], [], [], 15)
        line = proc.stdout.readline().strip() if ready else ''
        if line != 'READY':
            proc.kill()
            raise AwError('unavailable', f'input helper not ready: {line[:80]!r}')
        self.proc = proc

    def cmd(self, line: str, timeout: float = 15.0) -> str:
        proc = self.proc
        if proc is None:
            raise RuntimeError('helper not started')
        try:
            proc.stdin.write(line + '\n')
            proc.stdin.flush()
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'helper write failed: {exc}') from None
        if not ready:
            raise RuntimeError('helper ack timeout')
        ack = proc.stdout.readline().strip()
        if not ack:
            raise RuntimeError('helper exited mid-batch')
        return ack

    def cancel(self) -> None:
        if self.running:
            try:
                self.cmd('C')
            except RuntimeError:
                self.abort()

    def abort(self) -> None:
        """Signal-safe: close stdin; the helper releases held input on EOF and exits."""
        proc = self.proc
        if proc is not None and proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    def stop(self) -> None:
        self.abort()
        if self.proc is not None:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


HELPER = Helper()


def run_batch(lines: list[str], generation: int, helper: Helper = HELPER) -> dict:
    """Run encoded input; recheck ownership before every line, release on any failure."""
    require_agent(generation)
    helper.start()
    ox, oy = helper.origin
    for line in lines:
        state = read_state()
        if state.get('owner') != 'agent' or state.get('generation') != generation:
            helper.cancel()
            raise AwError('stale_generation', 'control changed during the batch')
        if line.startswith('M ') and (ox or oy):
            x, y = map(int, line[2:].split())
            line = f'M {x - ox} {y - oy}'
        try:
            ack = helper.cmd(line)
        except RuntimeError as exc:
            helper.cancel()
            code = 'stale_generation' if read_state().get('generation') != generation else 'unavailable'
            raise AwError(code, str(exc)) from None
        if ack != 'OK':
            helper.cancel()
            raise AwError('unavailable', f'helper {ack[:80]!r}')
    return {'ok': True, 'acked': len(lines), 'generation': generation}


# -- capture -----------------------------------------------------------------

def screenshot(dest: Path, output: str | None = None, region=None, max_size=None) -> dict:
    """Capture global layout pixels with grim; return frame metadata."""
    if region is not None:
        if not isinstance(region, list) or len(region) != 4 or any(type(v) is not int for v in region):
            raise ValueError('region must be [x, y, width, height] in layout pixels')
        if region[2] <= 0 or region[3] <= 0:
            raise ValueError('region width and height must be positive')
        x, y, width, height = region
        name = output
    elif output == 'all':
        x, y, width, height = host.layout_box()
        name = 'all'
    else:
        monitor = host.monitor(output)
        x, y, width, height, name = monitor['x'], monitor['y'], monitor['w'], monitor['h'], monitor['name']
    options = ['-g', f'{x},{y} {width}x{height}']
    scale = 1.0
    if max_size is not None:
        if type(max_size) is not int or not 320 <= max_size <= 3840:
            raise ValueError('max_size must be 320–3840')
        scale = min(1.0, max_size / max(width, height))
        options += ['-s', str(scale)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    state = read_state()
    result = subprocess.run(['grim', *options, str(dest)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AwError('unavailable', f'grim failed: {result.stderr.strip()[:300]}')
    with dest.open('rb') as png:
        image_width, image_height = struct.unpack('>II', png.read(24)[16:24])
    return {'path': str(dest), 'generation': state.get('generation', 0), 'owner': state.get('owner', 'off'),
            'width': image_width, 'height': image_height, 'region': [x, y, width, height],
            'output': name, 'scale': scale}
