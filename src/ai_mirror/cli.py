"""The ai-mirror command. Every operation prints JSON for humans, agents and the bar."""
import argparse
import json
import subprocess
import sys

from . import api, control
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
    p = commands.add_parser('control', help='agent: allow agent input; off: revoke and release held keys')
    p.add_argument('mode', choices=['agent', 'off'])
    p = commands.add_parser('screenshot')
    p.add_argument('--out')
    p.add_argument('--output', help="monitor name or 'all' (default: focused)")
    p.add_argument('--region', type=region)
    p.add_argument('--max-size', dest='max_size', type=int)
    p = commands.add_parser('input')
    p.add_argument('--generation', type=int, required=True)
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
    return parser


def main(argv=None):
    args = vars(build_parser().parse_args(argv))
    op = args.pop('op').replace('-', '_')
    if op == 'mcp':
        from . import mcp
        return mcp.main()
    if op == 'launch' and args['argv'][:1] == ['--']:
        args['argv'] = args['argv'][1:]
    try:
        result = api.run(op, {k: v for k, v in args.items() if v is not None})
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('ok') is False else 0
    except (MirrorError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': {'code': getattr(exc, 'code', 'unavailable'), 'message': str(exc)}}))
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        control.HELPER.stop()  # a CLI batch never leaves keys held


if __name__ == '__main__':
    sys.exit(main())
