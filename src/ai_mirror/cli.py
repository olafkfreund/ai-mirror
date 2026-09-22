"""The ai-mirror command. Every operation prints JSON for humans, agents and the bar."""
import argparse
import json
import subprocess
import sys

from . import a11y, api, control
from .control import MirrorError


def region(value):
    parts = [int(p) for p in value.split(',')]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError('region is x,y,width,height')
    return parts


def build_parser():
    parser = argparse.ArgumentParser(prog='ai-mirror', description='Let an AI agent drive your Hyprland desktop')
    commands = parser.add_subparsers(dest='op', required=True)
    for name in ('status', 'doctor', 'windows', 'mcp'):
        commands.add_parser(name)
    p = commands.add_parser('control', help='agent: ask the human for control; off: revoke and release held keys; '
                                            'confirm/deny: answer the waiting request')
    p.add_argument('mode', choices=['agent', 'off', 'confirm', 'deny'])
    p.add_argument('id', nargs='?', help='the request id to answer (default: the one waiting)')
    p = commands.add_parser('screenshot')
    p.add_argument('--out')
    p.add_argument('--output', help="monitor name or 'all' (default: focused)")
    p.add_argument('--region', type=region)
    p.add_argument('--max-size', dest='max_size', type=int)
    p = commands.add_parser('input')
    p.add_argument('--generation', type=int, required=True)
    # Typing must name its target (#24), so without this the CLI could only
    # click (#26). A window's address, or a layer surface's, from `windows`.
    p.add_argument('--window', help='address of the window, or surface under layers, to type into (from windows)')
    p.add_argument('actions', type=json.loads, help='JSON action array; see docs/usage.md')
    p = commands.add_parser('window')
    p.add_argument('action', choices=['focus', 'close', 'float', 'center', 'fullscreen', 'workspace', 'resize'])
    p.add_argument('address')
    p.add_argument('--workspace')
    p.add_argument('--mode', choices=['fullscreen', 'maximized'])
    p.add_argument('--w', type=int)
    p.add_argument('--h', type=int)
    p = commands.add_parser('launch')
    p.add_argument('argv', nargs=argparse.REMAINDER, help='program and arguments after --')
    p = commands.add_parser('clipboard')
    p.add_argument('action', choices=['read', 'write'])
    p.add_argument('text', nargs='?')
    p = commands.add_parser('a11y-tree')
    p.add_argument('--app')
    p.add_argument('--depth', type=int, default=12)
    p.add_argument('--max-nodes', dest='max_nodes', type=int, default=400)
    p = commands.add_parser('a11y-find')
    p.add_argument('--name')
    p.add_argument('--role')
    p.add_argument('--app')
    p.add_argument('--limit', type=int, default=20)
    p = commands.add_parser('a11y-act')
    p.add_argument('node')
    p.add_argument('action')
    p.add_argument('--text')
    p = commands.add_parser('wait', help='confirm a prerequisite holds before acting on it')
    p.add_argument('--layer', help='a layer surface with this namespace, e.g. nixarchy-pkg-menu')
    p.add_argument('--window-class', dest='window_class')
    p.add_argument('--window-title', dest='window_title', help='substring match')
    p.add_argument('--workspace')
    p.add_argument('--monitor', help='this monitor is focused')
    p.add_argument('--layout', help='every keyboard reports this keymap')
    p.add_argument('--absent', action='store_true', help='wait for it to stop holding')
    p.add_argument('--timeout', type=float)
    p = commands.add_parser('index', help='what this host looks like: keys, plugins, gotchas')
    p.add_argument('--section', action='append',
                   help='add a section (repeatable); default is state, keys, plugins, nav, gotchas')
    p.add_argument('--find', help='search the omarchy-* command summaries')
    p.add_argument('--json', action='store_true', help='JSON instead of Markdown')
    return parser


def main(argv=None):
    args = vars(build_parser().parse_args(argv))
    op = args.pop('op').replace('-', '_')
    if op == 'mcp':
        from . import mcp
        return mcp.main()
    if op == 'launch' and args['argv'][:1] == ['--']:
        args['argv'] = args['argv'][1:]
    # The index is the one operation whose usual reader is a language model, so
    # it prints Markdown unless a program asks for JSON.
    as_markdown = op == 'index' and not args.pop('json', False)
    try:
        # `control agent` is an agent asking, whatever the transport: the person
        # at the keyboard answers it with confirm/deny, and the dialog tells them
        # who is asking (#34). `control off`, which the Super+Shift+Escape binding
        # runs, really is the human.
        by = 'agent' if op == 'control' and args.get('mode') == 'agent' else 'human'
        result = api.run(op, {k: v for k, v in args.items() if v is not None}, by=by)
        if as_markdown:
            from . import index
            sys.stdout.write(index.render(result))
            return 0
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('ok') is False else 0
    except (MirrorError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        error = {'code': getattr(exc, 'code', 'unavailable'), 'message': str(exc)}
        error.update(getattr(exc, 'details', None) or {})
        print(json.dumps({'error': error}))
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        control.HELPER.stop()  # a CLI batch never leaves keys held
        a11y.release_bus()  # nor accessibility switched on just to read it


if __name__ == '__main__':
    sys.exit(main())
