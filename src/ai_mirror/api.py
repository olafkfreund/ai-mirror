"""One operation dispatcher shared by the CLI, the bar widget and MCP."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import control, host
from .control import MirrorError
from .input import encode

MUTATING = {'input', 'window', 'launch', 'a11y_act'}


def doctor() -> dict:
    missing = [c for c in ('hyprctl', 'grim', 'wl-copy', 'wl-paste', 'busctl') if not shutil.which(c)]
    try:
        control.helper_binary()
    except MirrorError:
        missing.append('ai-mirror-input')
    return {'ok': not missing, 'missing': missing}


def _generation(args) -> int:
    generation = args.get('generation')
    if type(generation) is not int:
        raise ValueError('generation (from status or a fresh screenshot) is required')
    return generation


def run(op: str, args: dict | None = None, by: str = 'human') -> dict:
    args = args or {}
    if op == 'doctor':
        return doctor()
    if op == 'status':
        state = control.read_state()
        return {**state, 'monitors': host.monitors()}
    if op == 'control':
        return control.set_owner(args.get('mode'), by)
    if op == 'screenshot':
        dest = Path(args.get('out') or control.root() / 'shot.png').absolute()
        return control.screenshot(dest, args.get('output'), args.get('region'), args.get('max_size'))
    if op == 'windows':
        return {'windows': host.windows()}
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
            return control.run_batch(encode(args.get('actions')), generation)
        if op == 'window':
            dispatcher = host.window_dispatch(args.get('action'), args.get('address'), args.get('workspace'),
                                              args.get('w'), args.get('h'), args.get('mode'))
            host.ctl('dispatch', dispatcher)
            return {'ok': True, 'action': args.get('action'), 'address': args.get('address')}
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
