"""One operation dispatcher shared by the CLI, the bar widget and MCP."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import control, host
from .control import MirrorError
from .input import encode, needs_window

MUTATING = {'input', 'window', 'launch', 'a11y_act'}
# Ungated reads. An agent doing any of these lights the watching mark in the bar.
OBSERVING = {'screenshot', 'windows', 'clipboard', 'a11y_tree', 'a11y_find', 'wait', 'index'}


def _window(args: dict) -> dict:
    """Read, act, confirm (#53): the dispatch returning says nothing happened."""
    from . import wait
    action, address, enabled = args.get('action'), args.get('address'), args.get('enabled')
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError('enabled must be true or false')
    timeout = wait._timeout(args.get('timeout'), default=1.5)
    dispatcher = host.window_dispatch(action, address, args.get('workspace'),
                                      args.get('w'), args.get('h'), args.get('mode'))

    def row_of():
        return next((r for r in host.windows() if r['address'] == address), None)

    before = row_of()
    if before is None:
        raise MirrorError('no_such_window', f'no window {address}: call windows for current addresses')
    if action in ('resize', 'center') and not before['floating']:
        raise MirrorError('invalid', 'resize/center applies to floating windows; this one is tiled. '
                                     'Float it first; do not retry as is.')
    size = [args.get('w'), args.get('h')]
    target = enabled if enabled is not None else not before['floating']
    holds = {  # already true: nothing to dispatch
        'focus': lambda: host.focused_address() == address,
        'workspace': lambda: before['workspace'] == args.get('workspace'),
        'resize': lambda: before['size'] == size,
        'float': lambda: enabled is not None and before['floating'] == enabled,
    }
    done = {  # true once the action has landed
        'focus': lambda r: host.focused_address() == address,
        'close': lambda r: r is None,
        'float': lambda r: r is not None and r['floating'] == target,
        'workspace': lambda r: r is not None and r['workspace'] == args.get('workspace'),
        'resize': lambda r: r is not None and r['size'] == size,
        'fullscreen': lambda r: r is not None and r['fullscreen'] != before['fullscreen'],
        'center': lambda r: r is not None,  # position not checked; a closed window is not_confirmed
    }
    ok = {'ok': True, 'action': action, 'address': address}
    if action in holds and holds[action]():
        return {**ok, 'changed': False, 'verified': True, 'before': before, 'after': before, 'waited_ms': 0}
    host.ctl('dispatch', dispatcher)

    after = None

    def check(budget):
        nonlocal after
        after = row_of()
        return done[action](after)

    result = wait.poll(check, timeout)
    if result['result'] == 'unavailable':
        raise MirrorError('unavailable', result['reason'], details={'before': before})
    if result['result'] == 'not_confirmed':
        raise MirrorError('not_confirmed', f'did not reach the requested state within {timeout:g}s; '
                                           'it may still land -- call windows before retrying',
                          details={'before': before, 'after': after, 'waited_ms': result['waited_ms']})
    center = action == 'center'
    return {**ok, 'changed': after['at'] != before['at'] if center else after != before,
            'verified': None if center else True, 'before': before, 'after': after,
            'waited_ms': result['waited_ms']}


SESSION_VARS = ('HYPRLAND_INSTANCE_SIGNATURE', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR')


def doctor() -> dict:
    """Binaries, the helper, and whether the compositor can actually be reached.

    The binaries were always the easy half. Every subcommand goes through
    Hyprland, so a session that cannot reach it fails at everything -- and
    until #32 this reported ok in exactly that case, which is the one case a
    self-check exists for. A non-login shell (ssh, a systemd unit, a cron job)
    is the usual way to arrive here without a session.
    """
    missing = [c for c in ('hyprctl', 'grim', 'wl-copy', 'wl-paste', 'busctl') if not shutil.which(c)]
    try:
        control.helper_binary()
    except MirrorError:
        missing.append('ai-mirror-input')
    report = {'missing': missing}
    try:
        host.focused_address()
        report['compositor'] = 'reachable'
    except (MirrorError, RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        unset = [name for name in SESSION_VARS if not os.environ.get(name)]
        report['compositor'] = str(exc)
        if unset:
            report['unset'] = unset
            report['hint'] = ('this shell has no desktop session; export ' + ', '.join(unset) +
                              ' from the running one (see demo/rz for a worked example)')
    return {'ok': not missing and report['compositor'] == 'reachable', **report}


def _generation(args) -> int:
    generation = args.get('generation')
    if type(generation) is not int:
        raise ValueError('generation (from status or a fresh screenshot) is required')
    return generation


def run(op: str, args: dict | None = None, by: str = 'human') -> dict:
    args = args or {}
    if by == 'agent' and op in OBSERVING:
        control.watch()
    if op == 'doctor':
        return doctor()
    if op == 'status':
        state = control.read_state()
        # `audit` names the verb rather than embedding the trail. A reader
        # asking "what happened" tries status first, and a pointer is the
        # difference between discoverable and merely present; embedding a
        # slice would put the trail in every status call including the MCP
        # one, which is the CLI-only decision in through a side door.
        return {**state, 'monitors': host.monitors(), 'audit': 'ai-mirror audit'}
    if op == 'audit':
        # NOT in OBSERVING: that marks the bar as watched for by='agent'
        # calls, and there is no agent path here -- `audit` is deliberately
        # absent from mcp.SPECS. See plan/2026-09-27-44-audit-verb.md, and
        # the test that asserts the absence so it stays a decision.
        result = control.read_audit(int(args.get('n', 20)))
        since = control.boot_time()
        return {**result, **({'since': since} if since else {})}
    if op == 'control':
        mode = args.get('mode')
        if mode in ('confirm', 'deny'):
            # Only the human answers, and the agent reaches this dispatcher with by='agent'.
            if by == 'agent':
                raise MirrorError('not_owner', 'only the person at the keyboard confirms or denies a request')
            request = args.get('id') or control.read_state().get('request', {}).get('id')
            return control.confirm_request(request) if mode == 'confirm' else control.deny_request(request)
        return control.set_owner(mode, by)
    if op == 'screenshot':
        dest = Path(args.get('out') or control.root() / 'shot.png').absolute()
        return control.screenshot(dest, args.get('output'), args.get('region'), args.get('max_size'))
    if op == 'windows':
        # Layer surfaces too: a menu or panel is not a window, and it is what
        # an agent types into once it has opened one (#26).
        return {'windows': host.windows(), 'layers': host.layers()}
    if op == 'clipboard':
        if args.get('action') == 'read':
            result = subprocess.run(['wl-paste', '--no-newline'], capture_output=True, timeout=10)
            data = result.stdout[:65536].decode('utf-8', 'replace') if result.returncode == 0 else ''
            return {'text': data, 'truncated': len(result.stdout) > 65536}
        if args.get('action') == 'write':
            if by == 'agent':
                control.require_agent(control.read_state().get('generation'))
            text = args.get('text')
            if not isinstance(text, str) or len(text.encode()) > 1 << 20:
                raise ValueError('text must be a string up to 1 MiB')
            # wl-copy forks a daemon that serves the clipboard; it must not inherit our
            # stdout, which is the MCP JSON-RPC channel.
            subprocess.run(['wl-copy'], input=text.encode(), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=10)
            return {'ok': True}
        raise ValueError('action must be read or write')
    if op == 'a11y_tree':
        from . import a11y
        return a11y.tree(args.get('app'), args.get('depth', 12), args.get('max_nodes', 400))
    if op == 'a11y_find':
        from . import a11y
        return a11y.find(args.get('name'), args.get('role'), args.get('app'), args.get('limit', 20))
    if op == 'wait':
        # Read-only, and outside the ownership gate for the same reason as
        # index: observing is not acting. A caller whose control was revoked
        # already fails on its next input with not_owner.
        from . import wait
        return wait.until(args)
    if op == 'index':
        # Read-only, and deliberately outside the ownership gate: orienting
        # before asking for control is the point of having it.
        from . import index
        return index.build(args)
    if op in MUTATING:
        # Agents always need a current grant; the human using the CLI does too, so
        # scripted input never lands while control is off.
        generation = args.get('generation', control.read_state().get('generation')) if op != 'input' else _generation(args)
        control.require_agent(generation)
        if op == 'input':
            actions = args.get('actions')
            window = args.get('window')
            if needs_window(actions) and not window:
                # A model told only "no" retries; this one says what to do.
                raise MirrorError('invalid', 'typing must name the window it types into: '
                                             'call windows, pick the address of the window you '
                                             'mean -- or, for a menu, panel or launcher, of the '
                                             'surface under layers -- and pass it as window. Pointer actions do '
                                             'not need it.')
            lines, owners = encode(actions, with_owners=True)
            return control.run_batch(lines, generation, window=window, owners=owners)
        if op == 'window':
            return _window(args)
        if op == 'launch':
            argv = args.get('argv')
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and '\0' not in a for a in argv):
                raise ValueError('argv must be a non-empty array of strings')
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            return {'ok': True, 'pid': proc.pid}
        if op == 'a11y_act':
            from . import a11y
            return a11y.act(args.get('node'), args.get('action'), args.get('text'), args.get('expect'))
    raise ValueError(f'Unknown operation: {op}')
