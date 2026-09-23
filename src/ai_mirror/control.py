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
import secrets
import struct
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import guard, host, privacy

REPO_HELPER = Path(__file__).resolve().parents[2] / 'build/ai-mirror-input'


class MirrorError(Exception):
    """Structured error with a stable machine-readable code.

    `details` carries machine-readable facts the message states in prose --
    how much of a batch was delivered, say (#30). A caller that acts on the
    numbers must not have to parse the sentence.
    """

    def __init__(self, code: str, detail: str = '', details: dict | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(code if not detail else f'{code}: {detail}')


def root() -> Path:
    base = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    path = Path(base) / 'ai-mirror'
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


_HELD: set[str] = set()


@contextmanager
def locked(name: str):
    # Re-entrant: flock on a second fd from the same process would deadlock, and
    # read_state() writes an expiry from inside set_owner's lock.
    if name in _HELD:
        yield
        return
    with open(root() / f'{name}.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _HELD.add(name)
        try:
            yield
        finally:
            _HELD.discard(name)


def proc_start(pid: int) -> str | None:
    """Process birth time; guards pid files against pid reuse."""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (OSError, IndexError):
        return None


# -- control state -----------------------------------------------------------

REQUEST_TTL = 30       # seconds a request waits for the human before it lapses
IDLE_LIMIT = 600       # seconds a grant survives without the agent using it


# A request nobody answers usually means nothing drew the dialog, so say where it comes from.
LAPSED = ('nobody answered the request within 30s; the ai-mirror bar widget draws the dialog '
          '(omarchy plugin enable olafkfreund.ai-mirror --section right)')


def now() -> float:
    """The clock, in one place, so the tests can move it."""
    return time.time()


def stamp() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def audit(event: str, **fields) -> None:
    """One JSON object per line; the record of who asked and who answered."""
    line = json.dumps({'event': event, 'at': stamp(), **fields}, sort_keys=True)
    path = root() / 'audit.jsonl'
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def _load() -> dict:
    try:
        state = json.loads((root() / 'state.json').read_text())
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {'owner': 'off', 'generation': 0}


def _a11y_enable() -> dict:
    """Expose accessibility for the agent's tenure, recording what was already on.

    Never blocks taking control: input is the point of control and a11y is a
    bonus, so a missing busctl must not cost the agent its hands. The failure
    surfaces where it matters, when a11y is actually read.
    """
    from . import a11y  # late: a11y imports MirrorError from this module
    try:
        return a11y.enable_bus()
    except MirrorError:
        return {}


def _a11y_restore(before: dict) -> None:
    """Put back only what we switched on, so a human's screen reader stays on."""
    from . import a11y
    for prop, was in (before or {}).items():
        if was is False:
            try:
                a11y.set_bus_property(prop, False)
            except MirrorError:
                pass


def _write(state: dict) -> dict:
    atomic_write_json(root() / 'state.json', state)
    return state


def _lapsed(state: dict) -> bool:
    return state.get('owner') == 'pending' and now() > state.get('request', {}).get('expires', 0)


def read_state() -> dict:
    """The state as it stands, with a request nobody answered already lapsed."""
    state = _load()
    if not _lapsed(state):
        return state
    with locked('control'):
        state = _load()
        if not _lapsed(state):
            return state
        audit('expired', request=state['request'].get('id'), by=state['request'].get('by'))
        _a11y_restore(state.get('a11y_before') or {})
        return _write({'owner': 'off', 'generation': int(state.get('generation', 0)) + 1,
                       'since': stamp(), 'enabled_by': None, 'why': LAPSED})


def _holder_running(held_by) -> bool:
    """Whether the process recorded as holding control is still that process.

    A pid on its own is not an identity -- pids are reused -- so the birth time
    recorded with it has to match too. Anything that is not a well-formed
    record of a live process reads as "not running", which errs toward letting
    control be released rather than toward a desktop nobody can take back.
    """
    if not isinstance(held_by, dict):
        return False
    pid = held_by.get('pid')
    if not isinstance(pid, int):
        return False
    return proc_start(pid) == held_by.get('start') and held_by.get('start') is not None


def _may_release(state: dict) -> bool:
    """Whether an agent may end this grant (#40).

    The person at the keyboard is never asked this question -- their stop is
    unconditional, and `set_owner` only consults this for `by == 'agent'`.
    """
    if 'held_by' not in state:
        return True  # granted before #40; behaves as it always did
    held_by = state['held_by']
    if SERVER is not None and held_by == SERVER:
        return True  # our own grant
    if held_by is None:
        # A CLI caller holds it. No server speaks for that grant, and there is
        # no process to outlive: it ends with the idle timeout, the person, or
        # the same CLI.
        return False
    return not _holder_running(held_by)  # a holder that is gone holds nothing


def set_owner(mode: str, by: str) -> dict:
    """mode=agent asks the human; only confirm_request grants control."""
    if mode not in ('agent', 'off') or by not in ('agent', 'human'):
        raise ValueError('mode must be agent or off')
    with locked('control'):
        state = read_state()
        generation = int(state.get('generation', 0)) + 1
        if mode == 'agent':
            # Who is asking, so the grant can be told from anyone else's (#40).
            # None means a CLI caller: nobody's server speaks for that grant.
            request = {'id': secrets.token_hex(8), 'by': by, 'since': stamp(),
                       'expires': now() + REQUEST_TTL, 'server': SERVER}
            audit('requested', request=request['id'], by=by)
            pending = {'owner': 'pending', 'generation': generation, 'since': stamp(),
                       'enabled_by': None, 'request': request}
            # Carry the record across a re-request from a live grant. The
            # properties are already on, so recapturing after the confirm would
            # record what we set ourselves and `off` would restore the wrong
            # thing. Asking again must not lose what asking the first time found.
            if state.get('a11y_before'):
                pending['a11y_before'] = state['a11y_before']
            state = _write(pending)
        else:
            if by == 'agent' and state.get('owner') in ('agent', 'pending') and not _may_release(state):
                holder = state.get('held_by')
                whose = f"another agent (server pid {holder['pid']})" if holder else 'a caller with no server'
                raise MirrorError('not_owner',
                                  f'control is held by {whose}, so it was not released. Ask the '
                                  'person at the keyboard to stop it, or wait for it to end.')
            _a11y_restore(state.get('a11y_before') or {})
            audit('off', by=by, was=state.get('owner'))
            state = _write({'owner': 'off', 'generation': generation, 'since': stamp(), 'enabled_by': None})
    if mode == 'off':
        signal_servers()
    return state


def _baseline_layers() -> list[str] | None:
    """Namespaces of the surfaces already on screen when control was granted.

    Hyprland cannot say which surface holds the keyboard (#29), so this is the
    next best fact: anything mapped at the moment the human said yes is part of
    the desktop's furniture -- the bar, the background -- and anything that
    appears afterwards is a panel, a launcher or a notification that may have
    taken the keyboard. A snapshot rather than a namespace allowlist, which
    would have to be updated for every plugin ever installed.

    A query that fails returns None and the key is left out, so the check is
    skipped rather than treating every surface as new: "we could not look"
    must not become "everything is suspicious", which would refuse all typing
    for the life of the grant.
    """
    try:
        return sorted({str(one.get('namespace') or '') for one in host.layers()})
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def _answer(request_id: str, granted: bool) -> dict:
    with locked('control'):
        state = read_state()
        request = state.get('request') or {}
        if state.get('owner') != 'pending' or not request_id or request_id != request.get('id'):
            raise MirrorError('bad_request', 'no request with that id is waiting; ask again')
        generation = int(state.get('generation', 0)) + 1
        audit('confirmed' if granted else 'denied', request=request_id, by=request.get('by'))
        if not granted:
            _a11y_restore(state.get('a11y_before') or {})
            return _write({'owner': 'off', 'generation': generation, 'since': stamp(), 'enabled_by': None})
        # Accessibility is switched on here rather than in set_owner: under #11
        # an agent that merely asks has not been granted anything, and must not
        # turn the bus on before the human has answered.
        granted_state = {'owner': 'agent', 'generation': generation, 'since': stamp(),
                         'enabled_by': 'human-confirmed', 'request_by': request.get('by'),
                         'last_input': now(), 'held_by': request.get('server')}
        baseline = _baseline_layers()
        if baseline is not None:
            granted_state['baseline_layers'] = baseline
        a11y_before = state.get('a11y_before') or _a11y_enable()
        if a11y_before:
            granted_state['a11y_before'] = a11y_before
        return _write(granted_state)


def confirm_request(request_id: str) -> dict:
    return _answer(request_id, True)


def deny_request(request_id: str) -> dict:
    return _answer(request_id, False)


def require_agent(generation: int) -> dict:
    state = read_state()
    if state.get('owner') == 'pending':
        raise MirrorError('not_owner', 'a human has been asked; poll status until owner is agent or off')
    if state.get('owner') != 'agent':
        raise MirrorError('not_owner', state.get('why')
                          or 'agent control is off; call control with mode agent to ask the human')
    if now() - state.get('last_input', 0) > IDLE_LIMIT:
        with locked('control'):
            audit('idle', by=state.get('request_by'))
            _write({'owner': 'off', 'generation': int(state.get('generation', 0)) + 1,
                    'since': stamp(), 'enabled_by': None})
        raise MirrorError('not_owner', f'the grant went unused for {IDLE_LIMIT} seconds; ask again')
    if generation != state.get('generation'):
        raise MirrorError('stale_generation', f"have {state.get('generation')}, want {generation}; observe again")
    if now() - state.get('last_input', 0) > 60:  # ponytail: coarse, so a drag is not a write per batch
        with locked('control'):
            _write({**state, 'last_input': now()})
    return state


def watch() -> None:
    """The moment an agent last looked. The bar shows a mark while this is fresh."""
    (root() / 'watching').write_text(f'{now():.0f}\n')


# -- MCP server registry for the kill switch ---------------------------------

def servers_dir() -> Path:
    path = root() / 'mcp.d'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


SERVER: dict | None = None  # this process's identity while it serves, for #40


def register_server() -> None:
    global SERVER
    pid = os.getpid()
    SERVER = {'pid': pid, 'start': proc_start(pid)}
    atomic_write_json(servers_dir() / f'{pid}.json', dict(SERVER))


def unregister_server() -> None:
    global SERVER
    SERVER = None
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
    found = os.environ.get('AI_MIRROR_HELPER') or shutil.which('ai-mirror-input')
    if found:
        return found
    if REPO_HELPER.is_file():
        return str(REPO_HELPER)
    raise MirrorError('unavailable', 'ai-mirror-input helper not found (install the flake package or build src/ai_mirror_input)')


class Helper:
    """One ai-mirror-input process. Closing its stdin makes it release everything and exit."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.origin = (0, 0)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.running:
            return
        guard.check('control.Helper.start', 'control.HELPER with a fake helper')
        box = host.layout_box()
        self.origin = box[:2]
        env = dict(os.environ, AI_MIRROR_EXTENT_W=str(box[2]), AI_MIRROR_EXTENT_H=str(box[3]))
        proc = subprocess.Popen([helper_binary()], env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1, close_fds=True)
        ready, _, _ = select.select([proc.stdout], [], [], 15)
        line = proc.stdout.readline().strip() if ready else ''
        if line != 'READY':
            proc.kill()
            raise MirrorError('unavailable', f'input helper not ready: {line[:80]!r}')
        self.proc = proc

    def cmd(self, line: str, timeout: float = 15.0) -> str:
        guard.check('control.Helper.cmd', 'control.HELPER with a fake helper')
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


def _require_focus(window: str) -> None:
    """Refuse unless the focused window is exactly the one the caller named.

    Refuses with `wrong_target`, not `stale_generation` (#31): nothing has been
    revoked and no generation has moved. The caller should observe and aim at
    the window it meant, which is a different response from "you no longer have
    control", and an agent told the latter stops instead.

    Positive by construction: one value proceeds. An empty workspace, a window
    that closed, a different window and a query that could not be answered all
    arrive here as "not that address", so nothing depends on knowing which of
    them Hyprland produces. The reason is chosen AFTER the refusal, never as
    part of deciding it -- that ordering is what keeps "we could not tell" from
    quietly becoming "nothing is wrong".
    """
    try:
        focused = host.focused_address()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise MirrorError('unavailable', f'could not read which window has focus: {exc}') from None
    if focused != window:
        raise MirrorError('wrong_target',
                          f'focus is {focused or "no window"}, not {window}; input was NOT sent. '
                          'Observe again and target the window you mean.')
    _refuse_new_surfaces(window)


KEYBOARD_LEVEL = 2  # top and overlay; a surface below cannot take the keyboard from a window
DEPARTED_CAP = 32   # a message aid, not a ledger


def _forget_departed(departed: list, gone) -> list:
    """The namespaces that were part of the desktop when control was granted and are not now.

    Kept so a refusal can tell a caller which shape it is looking at: a surface
    that appeared out of nowhere, or one that was furniture, went, and came
    back (#39). The second is the more suspicious of the two and reads
    differently. Capped, oldest first, because it exists to word a sentence.
    """
    kept = [name for name in departed if name not in gone]
    return (kept + sorted(gone))[-DEPARTED_CAP:]


def _refuse_new_surfaces(window: str) -> None:
    """Refuse a window-addressed keystroke while a surface mapped since the grant is up.

    The focused window is not the whole answer to "where will this land": an
    overlay above it can hold the keyboard while Hyprland still reports the
    window as focused, and then the keystroke goes somewhere the result names
    wrongly (#29). Nothing can be queried to settle it, so the honest move is
    to refuse and say which surface is in the way -- the caller can wait for it
    to go, or address it directly.

    Surfaces that have been mapped continuously since control was granted are
    not in the way: they are the shell the desktop always has up. Presence at
    the instant of the grant is not enough (#39) -- the dialog the person
    clicked to confirm is itself a surface, and so is any notification that
    happened to be up, and treating either as furniture for the life of the
    grant exempts exactly what this exists to refuse.
    """
    state = read_state()
    baseline = state.get('baseline_layers')
    if baseline is None:
        return  # granted before this check existed; nothing to compare against
    try:
        mapped = host.layers()
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        return  # a failed query is not evidence of a surface; _require_focus already passed
    # Every level, not just KEYBOARD_LEVEL and above: omarchy-background sits at
    # 0, and dropping it for being below the threshold this refusal uses would
    # make the wallpaper "new" on the first check and refuse everything after.
    present = {str(one.get('namespace') or '') for one in mapped}
    still = [name for name in baseline if name in present]
    departed = state.get('baseline_departed') or []
    if len(still) != len(baseline):
        gone = set(baseline) - present
        departed = _forget_departed(departed, gone)
        with locked('control'):
            # Re-read inside the lock: a grant can end between the read above
            # and here, and writing then would resurrect a dead grant's state.
            fresh = read_state()
            if fresh.get('generation') == state.get('generation'):
                _write({**fresh, 'baseline_layers': still, 'baseline_departed': departed})
    new = [one for one in mapped
           if one.get('level', 0) >= KEYBOARD_LEVEL and str(one.get('namespace') or '') not in still]
    if new:
        # Two shapes, and the second is the more suspicious: something that was
        # part of the desktop when control was granted, went, and is back (#39).
        returned = [one for one in new if str(one.get('namespace') or '') in departed]
        appeared = [one for one in new if one not in returned]
        def _names(surfaces):
            return ', '.join(f'{one["namespace"] or "?"} ({one["address"]})' for one in surfaces)
        parts = []
        if appeared:
            parts.append(f'{_names(appeared)} opened since control was granted')
        if returned:
            parts.append(f'{_names(returned)} went away and came back since control was granted, '
                         'so it no longer counts as part of the desktop')
        may = 'It may hold the keyboard' if len(new) == 1 else 'Any of them may hold the keyboard'
        go = 'Wait for it to go' if len(new) == 1 else 'Wait for them to go'
        raise MirrorError('wrong_target',
                          f'{"; ".join(parts)}. {may}, so input for window {window} was NOT sent. '
                          f'{go}, or pass an address above as the window to type into it.')


def _require_layer(layer: dict, layers: list[dict]) -> str | None:
    """Refuse unless the named layer surface is the topmost thing on screen.

    Hyprland does not say which layer holds the keyboard (measured again on
    0.56.0: `layers -j` carries `address, alpha, h, namespace, pid, w, x, y`
    and nothing else), and `activewindow` keeps naming the window underneath
    an overlay that has taken the keyboard. #26 therefore also demanded that
    no window have focus -- and that never holds for a quickshell overlay, so
    the supported way to type into a panel could not succeed while the
    unsupported one (addressing the window) worked by accident (#29).

    What is left is the condition Hyprland can actually answer: no other
    surface is mapped at this one's level or above, on any monitor, so a
    surface that takes the keyboard from the top can only be this one. A
    window that still holds focus is no longer a refusal -- it is returned,
    so the result can name it as where these keys land if the surface does
    not take them. Delivered is still not accepted.
    """
    try:
        focused = host.focused_address()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise MirrorError('unavailable', f'could not read which window has focus: {exc}') from None
    rivals = [other for other in layers
              if other['address'] != layer['address'] and other['level'] >= layer['level']]
    if rivals:
        names = ', '.join(f'{r["namespace"] or "?"} ({r["address"]})' for r in rivals)
        raise MirrorError('wrong_target',
                          f'another surface is open at the same level or above: {names}; '
                          f'cannot tell which has the keyboard, so input was NOT sent. '
                          'Close it, or wait for it to go, and observe again.')
    return focused


def _require_target(window: str) -> dict | None:
    """Refuse unless `window` -- a window's address or a layer surface's -- has the keyboard.

    A mapped layer surface goes through _require_layer. Everything else goes
    through #24's _require_focus exactly as before, which is already positive:
    an address that is not a mapped window cannot be the focused one.

    A layer query that fails falls through to _require_focus too, and that is
    not failing open: if the target really was a surface, focus is "no
    window", which is not its address, and the keystroke is refused. Returns
    the layer, when it is one, so the result can name it.
    """
    try:
        layers = host.layers()
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        layers = []
    for layer in layers:
        if layer['address'] == window:
            focused = _require_layer(layer, layers)
            return dict(layer, focused_window=focused)
    _require_focus(window)
    return None


def _partial(exc: MirrorError, delivered: int, lines: list[str],
             owners: list[int] | None) -> MirrorError:
    """Restate a mid-batch refusal in terms of what already landed (#30).

    The recheck runs before every line, so a refusal on line N arrives after
    N-1 lines have been delivered. Saying "input was NOT sent" of the call is
    then false, and false in the direction that makes a caller retry -- and
    type a second time into a desktop that already has the first copy.

    Nothing is delivered on a refusal at line 0, so the original wording (and
    its code) is kept for that case, which is the common one.
    """
    if delivered == 0:
        return exc
    details = {'delivered': delivered, 'of': len(lines)}
    prefix = f'partial: {delivered} of {len(lines)} lines delivered'
    if owners:
        done = owners[delivered - 1] + (1 if delivered >= len(owners) or owners[delivered] != owners[delivered - 1] else 0)
        total = owners[-1] + 1
        details |= {'actions_completed': done, 'actions_total': total}
        prefix += f' (actions 1-{done} of {total} completed)' if done else f' (no action completed of {total})'
    reason = str(exc).split(': ', 1)[-1].split('; input was NOT sent')[0].rstrip('. ')
    return MirrorError(exc.code, f'{prefix}, then {reason}. The rest was not sent '
                       'and held keys were released.', details | exc.details)


def run_batch(lines: list[str], generation: int, helper: Helper = HELPER,
              window: str | None = None, owners: list[int] | None = None) -> dict:
    """Run encoded input; recheck ownership and focus before every line, release on any failure.

    `window` follows `helper` rather than preceding it because callers already
    pass the helper positionally. `owners` (from `encode(..., with_owners=True)`)
    lets a refusal say how far the batch got in actions, not just in lines.
    """
    require_agent(generation)
    helper.start()
    ox, oy = helper.origin
    surface = None
    delivered = 0
    for line in lines:
        state = read_state()
        if state.get('owner') != 'agent' or state.get('generation') != generation:
            helper.cancel()
            raise _partial(MirrorError('stale_generation', 'control changed during the batch'),
                           delivered, lines, owners)
        if window is not None:
            # Per line, for the same reason ownership is: a batch is not atomic
            # and the desktop moves underneath one.
            try:
                surface = _require_target(window)
            except MirrorError as exc:
                helper.cancel()
                raise _partial(exc, delivered, lines, owners) from None
        if line.startswith('M ') and (ox or oy):
            x, y = map(int, line[2:].split())
            line = f'M {x - ox} {y - oy}'
        try:
            ack = helper.cmd(line)
        except RuntimeError as exc:
            helper.cancel()
            code = 'stale_generation' if read_state().get('generation') != generation else 'unavailable'
            raise _partial(MirrorError(code, str(exc)), delivered, lines, owners) from None
        if ack != 'OK':
            helper.cancel()
            raise _partial(MirrorError('unavailable', f'helper {ack[:80]!r}'),
                           delivered, lines, owners)
        delivered += 1
    result = {'ok': True, 'acked': len(lines), 'generation': generation}
    if window is not None:
        result['window'] = window
        # Delivered is not accepted, and accepted is not done. The helper acked
        # the keystrokes; whether the application took them, and whether the
        # task happened, are things only a fresh observation can say.
        if surface:
            where = f'surface {surface["namespace"]} ({window}), the topmost surface on screen'
            if surface.get('focused_window'):
                where += (f'; window {surface["focused_window"]} still holds focus, so if that '
                          'surface does not take the keyboard these keys landed in that window')
        else:
            where = f'{window}, which still had focus'
        result['note'] = (f'delivered to {where}. Application acceptance and task '
                          'completion are NOT verified -- observe before reporting the outcome.')
    return result


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
    # Before grim, not after: every agent-visible frame comes through here,
    # including the one mcp.py base64s, so one check covers the surface rather
    # than each caller remembering. The code is its own, so an agent can tell a
    # refusal that will never succeed from a capture that merely failed.
    refusal = privacy.refuse((x, y, width, height), host.windows(),
                             host.visible_workspaces())
    if refusal:
        raise MirrorError('sensitive', refusal)
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
        raise MirrorError('unavailable', f'grim failed: {result.stderr.strip()[:300]}')
    with dest.open('rb') as png:
        image_width, image_height = struct.unpack('>II', png.read(24)[16:24])
    return {'path': str(dest), 'generation': state.get('generation', 0), 'owner': state.get('owner', 'off'),
            'width': image_width, 'height': image_height, 'region': [x, y, width, height],
            'output': name, 'scale': scale}
