"""The user's Hyprland session: monitors, windows and validated dispatchers."""
import json
import re
import subprocess

ADDRESS_RE = re.compile(r'0x[0-9a-f]{1,16}')
WORKSPACE_RE = re.compile(r'[0-9]{1,3}|special(:[A-Za-z0-9_-]{1,32})?')


def ctl(*args, timeout=10):
    # Callers with their own deadline pass what is left of it: a caller waiting
    # 0.1s for something must not be held for ten by one slow query.
    result = subprocess.run(['hyprctl', *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode or (args[0] == 'dispatch' and result.stdout.strip() != 'ok'):
        raise RuntimeError('Hyprland: ' + (result.stderr or result.stdout).strip())
    return result.stdout


def monitors() -> list[dict]:
    """Logical monitor rects in global layout coordinates."""
    rows = []
    for m in json.loads(ctl('monitors', '-j')):
        width, height = m['width'], m['height']
        if m.get('transform', 0) % 2:
            width, height = height, width
        rows.append({'name': m['name'], 'x': m['x'], 'y': m['y'],
                     'w': round(width / m['scale']), 'h': round(height / m['scale']),
                     'scale': m['scale'], 'focused': bool(m.get('focused'))})
    return rows


def layout_box(rows=None) -> tuple[int, int, int, int]:
    rows = rows if rows is not None else monitors()
    x0, y0 = min(m['x'] for m in rows), min(m['y'] for m in rows)
    x1, y1 = max(m['x'] + m['w'] for m in rows), max(m['y'] + m['h'] for m in rows)
    return x0, y0, x1 - x0, y1 - y0


def monitor(name=None) -> dict:
    rows = monitors()
    for m in rows:
        if (m['name'] == name) if name else m['focused']:
            return m
    if name:
        raise ValueError(f"unknown output {name!r}; use one of {[m['name'] for m in rows]} or 'all'")
    return rows[0]


def windows() -> list[dict]:
    keys = ('address', 'class', 'title', 'at', 'size', 'monitor', 'floating', 'fullscreen', 'focusHistoryID')
    rows = []
    for w in json.loads(ctl('clients', '-j')):
        if not w.get('mapped', True):
            continue
        row = {k: (w[k][:240] if isinstance(w[k], str) else w[k]) for k in keys if k in w}
        row['workspace'] = (w.get('workspace') or {}).get('name')
        rows.append(row)
    return rows


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer {low}..{high}')
    return value


def window_dispatch(action: str, address: str, workspace=None, w=None, h=None, mode=None) -> str:
    """Build one Lua dispatcher from validated tokens only; nothing free-form reaches Lua."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        raise ValueError('address must look like 0x55d1c2a3 (from windows)')
    target = f'window = "address:{address}"'
    if action == 'focus':
        return f'hl.dsp.focus({{ {target} }})'
    if action == 'close':
        return f'hl.dsp.window.close({{ {target} }})'
    if action == 'float':
        return f'hl.dsp.window.float({{ {target}, action = "toggle" }})'
    if action == 'center':
        return f'hl.dsp.window.center({{ {target} }})'
    if action == 'fullscreen':
        if mode not in (None, 'fullscreen', 'maximized'):
            raise ValueError('mode must be fullscreen or maximized')
        return f'hl.dsp.window.fullscreen({{ {target}, mode = "{mode or "fullscreen"}" }})'
    if action == 'workspace':
        if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
            raise ValueError('workspace must be a number or special[:name]')
        return f'hl.dsp.window.move({{ {target}, workspace = "{workspace}", follow = false }})'
    if action == 'resize':
        # ponytail: exact size only; relative/position moves added when an agent needs them
        return (f'hl.dsp.window.resize({{ {target}, x = {_int(w, "w", 1, 16384)}, '
                f'y = {_int(h, "h", 1, 16384)}, relative = false }})')
    raise ValueError('action must be focus, close, float, center, fullscreen, workspace or resize')
