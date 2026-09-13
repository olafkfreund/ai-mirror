"""Stdio MCP server: compact observations and frame-relative input on the real desktop."""
import base64
import copy
import json
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__, api, control
from .control import AwError

STR = {'type': 'string'}
INT = {'type': 'integer'}
KEYS = {'type': 'array', 'items': STR}
ACTION = {'type': 'object', 'properties': {
    'type': {'type': 'string', 'enum': ['move', 'click', 'drag', 'scroll', 'type', 'key',
                                        'key_down', 'key_up', 'mouse_down', 'mouse_up']},
    **{k: INT for k in ('x', 'y', 'to_x', 'to_y', 'dx', 'dy')},
    'path': {'type': 'array', 'items': {'type': 'array', 'items': INT, 'minItems': 2, 'maxItems': 2}, 'maxItems': 32},
    'button': {'type': 'string', 'enum': ['left', 'right', 'middle', 'back', 'forward']},
    'count': {'type': 'integer', 'enum': [1, 2, 3]},
    'text': STR, 'keys': KEYS, 'modifiers': KEYS,
}, 'required': ['type'], 'additionalProperties': False}
FRAMES = {}  # This connection's last 32 observations.
FRAME_NUMBER = 0
READ_ONLY = {'status', 'screenshot', 'windows', 'a11y_tree', 'a11y_find'}
DESTRUCTIVE = {'control', 'input', 'window', 'launch', 'a11y_act'}


class MethodNotFound(Exception):
    pass


def tool(name, description, properties=None, required=None):
    return {'name': name, 'description': description,
            'annotations': {'readOnlyHint': name in READ_ONLY, 'destructiveHint': name in DESTRUCTIVE},
            'inputSchema': {'type': 'object', 'properties': properties or {},
                            'required': required or [], 'additionalProperties': False}}


TOOLS = [
    tool('status', 'Control owner (agent/off), generation, and monitor layout in global pixels.'),
    tool('control', 'mode=agent takes keyboard/mouse control of the real desktop (the bar shows AGENT CONTROL); mode=off releases it. The human can revoke at any time.',
         {'mode': {'type': 'string', 'enum': ['agent', 'off']}}, ['mode']),
    tool('screenshot', 'Observe: PNG + frame id for input. output = monitor name or "all" (default focused). region [x,y,w,h] in global pixels zooms. Default longest edge 1280. image=false returns a file path.',
         {'output': STR, 'region': {'type': 'array', 'items': INT, 'minItems': 4, 'maxItems': 4},
          'max_size': {'type': 'integer', 'minimum': 320, 'maximum': 3840}, 'image': {'type': 'boolean'}}),
    tool('windows', 'List windows: address, class, title, global at/size, monitor, workspace. No image.'),
    tool('input', 'Act with frame + image-pixel coordinates (or generation + global pixels). Types: move, click (count 1-3), drag (to_x/to_y or path), scroll (dx/dy steps, optional x/y), type (Unicode), key (["CTRL","L"]), key_down/key_up, mouse_down/mouse_up. modifiers holds keys around an action. screenshot=true observes afterwards.',
         {'frame': STR, 'generation': INT, 'actions': {'type': 'array', 'items': ACTION, 'minItems': 1, 'maxItems': 16},
          'screenshot': {'type': 'boolean'}, 'wait_ms': {'type': 'integer', 'minimum': 0, 'maximum': 2000}}, ['actions']),
    tool('window', 'Window management by address from windows: focus, close, float (toggle), center, fullscreen (mode fullscreen|maximized), workspace (move to "3" or "special:name"), resize (w, h).',
         {'action': {'type': 'string', 'enum': ['focus', 'close', 'float', 'center', 'fullscreen', 'workspace', 'resize']},
          'address': STR, 'workspace': STR, 'mode': {'type': 'string', 'enum': ['fullscreen', 'maximized']},
          'w': INT, 'h': INT}, ['action', 'address']),
    tool('launch', 'Start an installed program, e.g. ["firefox", "https://example.com"]. No shell.',
         {'argv': {'type': 'array', 'items': STR, 'minItems': 1}}, ['argv']),
    tool('clipboard', 'Read or write the Wayland clipboard as text. Writing needs agent control.',
         {'action': {'type': 'string', 'enum': ['read', 'write']}, 'text': STR}, ['action']),
    tool('a11y_tree', 'Accessibility tree (roles, names, states, bounds, actions) — cheaper and more exact than pixels. Filter with app (name substring).',
         {'app': STR, 'depth': {'type': 'integer', 'minimum': 1, 'maximum': 64},
          'max_nodes': {'type': 'integer', 'minimum': 1, 'maximum': 2000}}),
    tool('a11y_find', 'Find accessible elements by name substring and/or exact role (e.g. "push button", "entry", "link").',
         {'name': STR, 'role': STR, 'app': STR, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}),
    tool('a11y_act', 'Act on an element id from a11y_tree/a11y_find: click, focus, set_text (text), or a named action. expect {role,name} guards against a changed UI.',
         {'node': STR, 'action': STR, 'text': STR, 'expect': {'type': 'object'}}, ['node', 'action']),
]
SPECS = {t['name']: t for t in TOOLS}
TYPES = {'string': str, 'array': list, 'object': dict}
INSTRUCTIONS = ('This server drives the user\'s REAL desktop. Call control with mode=agent before acting and '
                'mode=off when done. Prefer a11y_find/windows over screenshots. Use the frame from the latest '
                'screenshot for input. Any not_owner or stale_generation error means the human revoked or '
                'changed control: stop, observe again, and never retry blindly.')


def text(value):
    return {'type': 'text', 'text': json.dumps(value, ensure_ascii=False, separators=(',', ':'))}


def observe(args):
    global FRAME_NUMBER
    include_image = args.get('image', True)
    capture = {k: v for k, v in args.items() if k in ('output', 'region', 'max_size')}
    capture.setdefault('max_size', 1280)
    temp = None
    if include_image:
        with tempfile.NamedTemporaryFile(suffix='.png', prefix='sideyard-frame-', delete=False) as file:
            temp = Path(file.name)
        capture['out'] = str(temp)
    try:
        result = api.run('screenshot', capture)
        image = base64.b64encode(Path(result['path']).read_bytes()).decode() if include_image else None
    finally:
        if temp:
            temp.unlink(missing_ok=True)
    FRAME_NUMBER += 1
    frame = f'f{FRAME_NUMBER}'
    FRAMES[frame] = result
    if len(FRAMES) > 32:
        del FRAMES[next(iter(FRAMES))]
    meta = {k: result[k] for k in ('generation', 'owner', 'width', 'height', 'region', 'output')}
    meta['frame'] = frame
    if not include_image:
        meta['path'] = result['path']
    return [text(meta)] + ([{'type': 'image', 'mimeType': 'image/png', 'data': image}] if image else [])


def from_frame(args):
    """Map image-pixel coordinates of a frame to global layout pixels."""
    args = copy.deepcopy(args)
    frame = FRAMES.get(args.pop('frame', None))
    if frame is None:
        raise ValueError('Unknown frame; take a fresh screenshot')
    if 'generation' in args and args['generation'] != frame['generation']:
        raise ValueError('generation conflicts with frame')
    args['generation'] = frame['generation']
    ox, oy, width, height = frame['region']

    def mapped(value, origin, extent, pixels, key):
        if type(value) is not int or not 0 <= value < pixels:
            raise ValueError(f'{key} is outside the frame')
        return origin + min(extent - 1, round(value * extent / pixels))

    for action in args.get('actions', []):
        if not isinstance(action, dict):
            raise ValueError('Each action must be an object')
        for kx, ky in (('x', 'y'), ('to_x', 'to_y')):
            if kx in action:
                action[kx] = mapped(action[kx], ox, width, frame['width'], kx)
            if ky in action:
                action[ky] = mapped(action[ky], oy, height, frame['height'], ky)
        if isinstance(action.get('path'), list):
            action['path'] = [[mapped(p[0], ox, width, frame['width'], 'path x'),
                               mapped(p[1], oy, height, frame['height'], 'path y')]
                              if isinstance(p, list) and len(p) == 2 else p for p in action['path']]
    return args


def validate(name, args):
    spec = SPECS.get(name)
    if spec is None or not isinstance(args, dict):
        raise ValueError('Unknown tool or invalid arguments')
    schema = spec['inputSchema']
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise ValueError('Unexpected or missing arguments')
    for key, value in args.items():
        prop = schema['properties'][key]
        kind = prop['type']
        ok = (type(value) is int if kind == 'integer' else type(value) is bool if kind == 'boolean'
              else isinstance(value, TYPES[kind]))
        if not ok:
            raise ValueError(f'Invalid type for {key}')
        if ('enum' in prop and value not in prop['enum'] or
                'minimum' in prop and value < prop['minimum'] or
                'maximum' in prop and value > prop['maximum']):
            raise ValueError(f'Invalid value for {key}')


def call_tool(name, args):
    try:
        validate(name, args)
        if name == 'screenshot':
            return {'content': observe(args), 'isError': False}
        run_args = from_frame(args) if 'frame' in args else dict(args)
        followup = run_args.pop('screenshot', False)
        wait_ms = run_args.pop('wait_ms', 150)
        result = api.run(name, run_args, by='agent')
        content = [text(result)]
        if followup:
            time.sleep(wait_ms / 1000)
            try:
                content.extend(observe({}))
            except (AwError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                content.append(text({'observation_error': str(exc), 'note': 'Input completed; do not repeat it.'}))
        return {'content': content, 'isError': False}
    except Exception as exc:  # every tool failure is a result the agent can read, never a dead server
        return {'content': [text({'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)})], 'isError': True}


def dispatch(method, params):
    if method == 'initialize':
        requested = params.get('protocolVersion')
        return {'protocolVersion': requested if requested in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25') else '2025-11-25',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'sideyard', 'version': __version__},
                'instructions': INSTRUCTIONS}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        return call_tool(params.get('name'), params.get('arguments', {}))
    raise MethodNotFound(method)


def handle(line):
    request = None
    try:
        request = json.loads(line)
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
            raise ValueError('Invalid JSON-RPC request')
        if 'id' not in request:
            return None
        params = request.get('params', {})
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        response = {'result': dispatch(request['method'], params)}
    except json.JSONDecodeError:
        response = {'error': {'code': -32700, 'message': 'Parse error'}}
    except MethodNotFound:
        response = {'error': {'code': -32601, 'message': 'Method not found'}}
    except (TypeError, ValueError):
        response = {'error': {'code': -32600, 'message': 'Invalid request'}}
    except Exception as exc:
        response = {'error': {'code': -32603, 'message': f'Internal error: {type(exc).__name__}'}}
    response.update(jsonrpc='2.0', id=request.get('id') if isinstance(request, dict) else None)
    return response


def main():
    control.register_server()
    signal.signal(signal.SIGUSR1, lambda *_: control.HELPER.abort())
    try:
        for line in sys.stdin:
            response = handle(line)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        control.unregister_server()
        control.HELPER.stop()
        state = control.read_state()
        if state.get('owner') == 'agent' and state.get('enabled_by') == 'agent':
            control.set_owner('off', 'agent')  # an agent's grant ends with its server
    return 0
