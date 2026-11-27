"""Read a visible Herdr viewport under the calling transport's own grant."""
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from . import control, events, host, privacy
from .control import MirrorError

PROC = Path('/proc')
SESSION = re.compile(rb'[A-Za-z0-9._-]{1,64}')
PANE = re.compile(r'w[0-9]+:p[0-9]+')
TAB = re.compile(r'w[0-9]+:t[0-9]+')
MAX_ROWS = 500
MAX_BYTES = 64 * 1024
SOCKET_OVERRIDES = {b'HERDR_SOCKET_PATH', b'HERDR_CLIENT_SOCKET_PATH'}


def _grant(generation, mcp):
    state = control.read_state()
    holder = state.get('held_by')
    eligible = (events.held(state) if mcp else
                control.SERVER is None and 'held_by' in state and holder is None)
    if (not eligible or state.get('owner') != 'agent'
            or control.now() - state.get('last_input', 0) > control.IDLE_LIMIT):
        raise MirrorError('not_owner', "terminal read needs this caller's active agent grant")
    if generation != state.get('generation'):
        raise MirrorError('stale_generation', 'terminal read generation changed')
    return holder, state.get('since'), state.get('instance'), generation


def _window(address):
    try:
        wins = host.windows()
        win = next((w for w in wins if w['address'] == address), None)
        if win is None:
            raise MirrorError('no_such_window', 'window is gone')
        if category := privacy.kind(win.get('class', ''), win.get('title', '')):
            raise MirrorError('sensitive', category)

        (x, y), (w, h) = win['at'], win['size']
        pid, monitor_id, workspace = win['pid'], win['monitor'], win['workspace']
        rect = (x, y, w, h)
        visible = host.visible_workspaces()
        if workspace not in visible:
            raise MirrorError('invalid', 'window is on a hidden workspace')
        monitor = next((m for m in host.monitors() if m['id'] == monitor_id), None)
        if monitor is None:
            raise MirrorError('unavailable', 'window monitor is unavailable')
        mx, my, mw, mh = (monitor[k] for k in ('x', 'y', 'w', 'h'))
        if not (w > 0 and h > 0 and mx <= x < x + w <= mx + mw and my <= y < y + h <= my + mh):
            raise MirrorError('invalid', 'window is clipped')
        others = [other for other in wins if other['address'] != address]
        if privacy.covering(rect, others, visible):
            raise MirrorError('invalid', 'another window overlaps the terminal')
        stable = str(win.get('stableId', ''))
        if not re.fullmatch('[0-9a-f]+', stable):
            raise MirrorError('unavailable', 'window identity is unavailable')
        if type(pid) is not int or pid <= 0 or any(other.get('pid') == pid for other in others):
            raise MirrorError('unsupported', 'terminal window needs its own kitty process')
        return pid, (stable, monitor_id, monitor['name'], mx, my, mw, mh, workspace, rect)
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        raise MirrorError('unavailable', 'could not read compositor state') from None


def _children(pid):
    children = set()
    for task in (PROC / str(pid) / 'task').iterdir():
        try:
            children.update(map(int, (task / 'children').read_bytes().split()))
        except (FileNotFoundError, ProcessLookupError):
            # A live thread without this file means CONFIG_PROC_CHILDREN is missing.
            if task.exists():
                raise OSError('missing children interface') from None
    return children


def _client_session(process, *, count_attaches=False):
    try:
        argv = (process / 'cmdline').read_bytes().removesuffix(b'\0').split(b'\0')
    except (FileNotFoundError, ProcessLookupError):
        return None
    if os.path.basename(argv[0]) != b'herdr':
        return None
    args = argv[1:]
    if count_attaches and args[:2] != [b'session', b'attach']:
        # Count TUI transport helpers without admitting them as kitty targets.
        if args[-2:] == [b'remote-client-bridge', b'--idle-timeout-v1']:
            args = args[:-1]
        if args[-1:] in ([b'client'], [b'remote-client-bridge']) and args[:-1] != [b'--session']:
            args = args[:-1]
    match args:
        case []:
            return b'default', True
        case [b'--session', name]:
            pass
        case [option] if option.startswith(b'--session='):
            name = option[len(b'--session='):]
        case [b'session', b'attach', name] if count_attaches:
            pass
        case _:
            return None
    if SESSION.fullmatch(name) and name not in (b'.', b'..'):
        return name, False
    return None


def _client_env(process):
    env = {}
    for entry in (process / 'environ').read_bytes().split(b'\0'):
        key, _, value = entry.partition(b'=')
        if key in SOCKET_OVERRIDES or key in (b'HERDR_SESSION', b'HOME', b'XDG_CONFIG_HOME', b'XDG_STATE_HOME'):
            env[key] = value
    return env


def _config_home(env):
    if b'XDG_CONFIG_HOME' in env:
        return env[b'XDG_CONFIG_HOME']
    return os.path.join(env.get(b'HOME', b'.'), b'.config')


def _require_local_view(env, client_start):
    state_home = env.get(b'XDG_STATE_HOME', os.path.join(env.get(b'HOME', b'.'), b'.local/state'))
    if not os.path.isabs(state_home):
        raise MirrorError('unsupported', 'cannot identify the Herdr client state directory')
    if state_home == b'/proc/self':
        # Linux procfs cannot contain a saved endpoint catalog in this directory.
        return
    reopen = 'reopen Herdr in a local-only window with XDG_STATE_HOME=/proc/self'
    try:
        boot = next(int(line.split()[1]) for line in (PROC / 'stat').read_text().splitlines()
                    if line.startswith('btime '))
        started = boot * 10**9 + int(client_start) * 10**9 // os.sysconf('SC_CLK_TCK')
        # Herdr reloads asynchronously, so a removed profile can still be on screen.
        for app_dir in ('herdr', 'herdr-dev'):
            catalog = Path(os.fsdecode(state_home)) / app_dir / 'client/endpoints.json'
            for parent in catalog.parents:
                try:
                    if parent.stat().st_ctime_ns >= started:
                        raise MirrorError('unsupported', f'Herdr client state changed since it started. {reopen}')
                except FileNotFoundError:
                    continue
                break
            try:
                with open(catalog, 'rb', opener=_open_catalog) as file:
                    info = os.fstat(file.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('endpoint catalog is not a regular file')
                    data = file.read(MAX_BYTES + 1)
            except FileNotFoundError:
                continue
            if len(data) > MAX_BYTES:
                raise ValueError('endpoint catalog exceeds size limit')
            profiles = json.loads(data).get('ssh', [])
            if not isinstance(profiles, list) or any(type(profile['enabled']) is not bool for profile in profiles):
                raise ValueError('invalid endpoint catalog')
            if any(profile['enabled'] for profile in profiles) or info.st_ctime_ns >= started:
                raise MirrorError('unsupported', f'Herdr client can display a saved SSH endpoint. {reopen}')
    except (AttributeError, KeyError, OSError, StopIteration, TypeError, ValueError):
        raise MirrorError('unavailable', 'could not verify the Herdr client endpoint') from None


def _open_catalog(path, flags):
    return os.open(path, flags | os.O_NONBLOCK | os.O_NOFOLLOW)


def _start(process):
    start = control.proc_start(int(process.name))
    if start is None:
        process.stat()  # distinguish a vanished PID from an unreadable identity
        raise MirrorError('unavailable', 'could not read terminal process identity')
    return start


def _session(pid):
    kitty = PROC / str(pid)
    try:
        if (kitty / 'exe').readlink().name not in ('kitty', '.kitty-wrapped'):
            raise MirrorError('unsupported', 'terminal window must run in kitty')
        kitty_start = _start(kitty)
        clients = []
        for child in _children(pid):
            if found := _client_session(PROC / str(child)):
                clients.append((child, found[0]))
        if len(clients) != 1:
            raise MirrorError('unsupported', 'kitty needs one direct Herdr client')
        (client, session), = clients
        client_process = PROC / str(client)
        client_start = _start(client_process)

        matches = set()
        for process in PROC.iterdir():
            if not process.name.isdecimal():
                continue
            found = _client_session(process, count_attaches=True)
            if found is None:
                continue
            name, implicit = found
            try:
                if implicit or process == client_process:
                    env = _client_env(process)
                    if implicit:
                        # An implicit client can override the default socket through its environment.
                        redirect = env.get(b'HERDR_SESSION', b'default')
                        if (SOCKET_OVERRIDES.intersection(env)
                                or (redirect != b'default' and (name == session or redirect == session))):
                            raise MirrorError('unsupported', 'cannot identify an implicit Herdr session')
                    if process == client_process:
                        config = _config_home(env)
                        if not os.path.isabs(config) or config != _config_home(os.environb):
                            raise MirrorError('unsupported', 'Herdr client uses a different config directory')
                        _require_local_view(env, client_start)
            except (FileNotFoundError, ProcessLookupError):
                continue
            if name == session:
                matches.add(int(process.name))
        if matches != {client}:
            raise MirrorError('unsupported', 'cannot identify a unique Herdr session client')
        return session.decode('ascii'), (pid, kitty_start, client, client_start)
    except (FileNotFoundError, ProcessLookupError):
        raise MirrorError('unsupported', 'terminal process exited') from None
    except (OSError, ValueError):
        raise MirrorError('unavailable', 'could not read terminal process state') from None


def _herdr(session, *args):
    try:
        result = subprocess.run(['herdr', '--session', session, *args], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=2, check=True)
        return result.stdout
    except FileNotFoundError:
        raise MirrorError('unsupported', 'Herdr executable is unavailable') from None
    except (OSError, subprocess.SubprocessError):
        raise MirrorError('unavailable', 'Herdr command failed') from None


def _by_id(rows, key, pattern):
    if not isinstance(rows, list):
        raise ValueError('expected a list')
    indexed = {}
    for row in rows:
        ident = row[key]
        if not pattern.fullmatch(ident) or ident in indexed:
            raise ValueError('invalid or duplicate ID')
        indexed[ident] = row
    return indexed


def _panes(session, requested):
    try:
        response = json.loads(_herdr(session, 'api', 'snapshot'))
        result = response['result']
        if 'error' in response or result['type'] != 'session_snapshot':
            raise ValueError('wrong response type')
        snapshot = result['snapshot']
        tab, focused = snapshot['focused_tab_id'], snapshot['focused_pane_id']
        layout = _by_id(snapshot['layouts'], 'tab_id', TAB)[tab]
        metadata = _by_id(snapshot['panes'], 'pane_id', PANE)
        zoomed = layout['zoomed']
        panes = _by_id(layout['panes'], 'pane_id', PANE)
        if type(zoomed) is not bool or layout['focused_pane_id'] != focused or focused not in panes:
            raise ValueError('invalid focus or zoom')
        candidates = {}
        for pane, row in panes.items():
            if metadata[pane]['tab_id'] != tab:
                raise ValueError('pane belongs to a different tab')
            rect = {k: row['rect'][k] for k in ('x', 'y', 'width', 'height')}
            if (any(type(n) is not int or not 0 <= n <= 65535 for n in rect.values())
                    or row['focused'] is not (pane == focused)):
                raise ValueError('invalid pane layout')
            if not zoomed or pane == focused:
                candidates[pane] = {'pane': pane, 'rect': rect, 'focused': row['focused']}
        selected = focused if requested is None else requested
        if selected not in candidates:
            raise MirrorError('invalid', 'pane is outside the visible tab layout')
        chosen = metadata[selected]
        if chosen.get('agent') is not None or chosen.get('agent_session') is not None:
            raise MirrorError('sensitive', 'an agent pane')
        title = chosen.get('terminal_title')
        if title is not None and not isinstance(title, str):
            raise ValueError('invalid pane title')
        if category := privacy.kind('', title or ''):
            raise MirrorError('sensitive', category)
        return (tab, zoomed, candidates[selected]['pane']), list(candidates.values())
    except (KeyError, TypeError, ValueError):
        raise MirrorError('unavailable', 'invalid Herdr snapshot') from None


def _target(address, requested):
    pid, window = _window(address)
    session, processes = _session(pid)
    pane, candidates = _panes(session, requested)
    return (window, processes, session, pane), candidates


def _viewport(data):
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        raise MirrorError('unavailable', 'invalid Herdr viewport text') from None
    output = bytearray()
    rows = 0
    for line in io.BytesIO(data):
        if rows == MAX_ROWS or len(output) + len(line) > MAX_BYTES:
            if rows == 0:
                # The complete text was valid UTF-8, so only the cut character can be incomplete.
                return line[:MAX_BYTES].decode('utf-8', errors='ignore'), 1, True
            break
        output.extend(line)
        rows += 1
    return output.decode('utf-8'), rows, len(output) < len(data)


def read(address, generation, requested=None, *, mcp):
    if not isinstance(address, str) or not host.ADDRESS_RE.fullmatch(address):
        raise MirrorError('invalid', 'window must be an address from windows')
    if requested is not None and not isinstance(requested, str):
        raise MirrorError('invalid', 'pane must be an ID from the visible tab layout')
    grant = _grant(generation, mcp)
    target, _ = _target(address, requested)
    _, _, session, (_, _, selected) = target
    data = _herdr(session, 'pane', 'read', selected, '--source', 'visible', '--format', 'text')

    changed = 'target changed, read again'
    try:
        if _grant(generation, mcp) != grant:
            raise MirrorError('unavailable', changed)
        current, panes = _target(address, requested)
    except MirrorError as error:
        if error.code in ('sensitive', 'not_owner', 'stale_generation'):
            raise
        raise MirrorError('unavailable', changed) from None
    if current != target:
        raise MirrorError('unavailable', changed)
    text, rows, truncated = _viewport(data)
    _, _, _, (_, _, selected) = current
    result = {'window': address, 'pane': selected, 'text': text, 'rows': rows,
              'truncated': truncated, 'panes': panes, 'generation': generation}
    if _grant(generation, mcp) != grant:
        raise MirrorError('unavailable', changed)
    return result
