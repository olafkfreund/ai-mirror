"""AT-SPI accessibility tree: find controls by role/name and act on them without pixels.

Needs PyGObject + the at-spi2-core typelib (the flake package provides both).
Node ids are child-index paths from the desktop ("app.child.child…"); act()
re-resolves the path and refuses if role or name changed since it was read.
"""
from __future__ import annotations

import subprocess

from .control import MirrorError

STATES = ('enabled', 'focused', 'focusable', 'editable', 'checked', 'selected',
          'expanded', 'collapsed', 'pressed', 'sensitive', 'multi-line')
QUIET_ROLES = ('filler', 'panel', 'section', 'redundant object', 'unknown')
VISIT_CAP = 20000
A11Y_STATUS = ('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Status')
A11Y_PROPS = ('IsEnabled', 'ScreenReaderEnabled')


def _atspi():
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        raise MirrorError('unavailable', f'AT-SPI bindings missing ({exc}); use the flake package') from None
    return Atspi


def _busctl(verb: str, prop: str, *value: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(['busctl', '--user', verb, *A11Y_STATUS, prop, *value],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MirrorError('unavailable', f'accessibility bus unreachable ({exc})') from None


def bus_property(prop: str) -> bool | None:
    """What an org.a11y.Status property is set to now, or None if unreadable."""
    result = _busctl('get-property', prop)
    words = result.stdout.split()  # busctl prints `b true`
    return words[-1] == 'true' if result.returncode == 0 and words else None


def set_bus_property(prop: str, value: bool) -> None:
    result = _busctl('set-property', prop, 'b', 'true' if value else 'false')
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:120]
        raise MirrorError('unavailable', f'could not set {prop}: {detail}')


def enable_bus() -> dict[str, bool | None]:
    """Ask toolkits to expose accessibility; report what each property was before.

    Toolkits watch ScreenReaderEnabled, not IsEnabled. Setting only the latter
    leaves a tree of application and frame nodes with nothing underneath them,
    which is what #12 was. Apps started before this may still need a restart,
    and Chromium wants --force-renderer-accessibility whatever the bus says.
    """
    before = {}
    for prop in A11Y_PROPS:
        before[prop] = bus_property(prop)
        set_bus_property(prop, True)
    return before


def _call(fn, default=None):
    try:
        return fn()
    except Exception:  # GLib.Error from dead or misbehaving apps
        return default


def _node(acc, node_id: str, Atspi) -> dict:
    row = {'id': node_id, 'role': _call(acc.get_role_name, ''), 'name': (_call(acc.get_name, '') or '')[:120]}
    state_set = _call(acc.get_state_set)
    if state_set is not None:
        row['states'] = [s for s in STATES
                         if _call(lambda s=s: state_set.contains(getattr(Atspi.StateType, s.upper().replace('-', '_'))), False)]
    comp = _call(acc.get_component_iface)
    if comp is not None:
        rect = _call(lambda: comp.get_extents(Atspi.CoordType.SCREEN))
        if rect is not None and rect.width > 0 and rect.height > 0:
            row['bounds'] = [rect.x, rect.y, rect.width, rect.height]
    action = _call(acc.get_action_iface)
    if action is not None:
        row['actions'] = [_call(lambda i=i: action.get_action_name(i), '') for i in range(_call(action.get_n_actions, 0))]
    text = _call(acc.get_text_iface)
    if text is not None:
        count = _call(text.get_character_count, 0)
        if count:
            row['text'] = _call(lambda: text.get_text(0, min(count, 120)), '')
    return row


def _showing(acc, Atspi) -> bool:
    state_set = _call(acc.get_state_set)
    return state_set is None or _call(lambda: state_set.contains(Atspi.StateType.SHOWING), True)


def _walk(app: str | None, depth: int, enable: bool = True):
    """Yield (id, accessible, level) depth-first over showing nodes."""
    Atspi = _atspi()
    # enable_bus writes org.a11y.Status over busctl. A caller that promises
    # to only observe -- the index -- must be able to decline that.
    if enable:
        enable_bus()
    desktop = Atspi.get_desktop(0)
    visited = 0
    for index in range(_call(desktop.get_child_count, 0)):
        root = _call(lambda: desktop.get_child_at_index(index))
        if root is None or (app and app.lower() not in (_call(root.get_name, '') or '').lower()):
            continue
        stack = [(str(index), root, 0)]
        while stack:
            node_id, acc, level = stack.pop()
            visited += 1
            if visited > VISIT_CAP:
                return
            yield node_id, acc, level, Atspi
            if level < depth:
                children = []
                for i in range(_call(acc.get_child_count, 0)):
                    child = _call(lambda i=i: acc.get_child_at_index(i))
                    if child is not None and _showing(child, Atspi):
                        children.append((f'{node_id}.{i}', child, level + 1))
                stack.extend(reversed(children))


def tree(app: str | None = None, depth: int = 12, max_nodes: int = 400,
         enable: bool = True) -> dict:
    nodes, truncated = [], False
    for node_id, acc, level, Atspi in _walk(app, depth, enable):
        row = _node(acc, node_id, Atspi)
        if level and not row['name'] and row['role'] in QUIET_ROLES and 'text' not in row:
            continue
        if len(nodes) >= max_nodes:
            truncated = True
            break
        row['depth'] = level
        nodes.append(row)
    return {'nodes': nodes, 'truncated': truncated}


def find(name: str | None = None, role: str | None = None, app: str | None = None, limit: int = 20) -> dict:
    if not name and not role:
        raise ValueError('give name and/or role')
    matches = []
    for node_id, acc, _level, Atspi in _walk(app, 64):
        if name and name.lower() not in (_call(acc.get_name, '') or '').lower():
            continue
        if role and role.lower() != (_call(acc.get_role_name, '') or '').lower():
            continue
        matches.append(_node(acc, node_id, Atspi))
        if len(matches) >= limit:
            break
    return {'nodes': matches}


def resolve(node_id: str):
    Atspi = _atspi()
    parts = node_id.split('.') if isinstance(node_id, str) else []
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError('node must be an id from a11y_tree or a11y_find')
    acc = Atspi.get_desktop(0)
    for part in parts:
        acc = _call(lambda: acc.get_child_at_index(int(part)))
        if acc is None:
            raise MirrorError('stale_node', 'the element is gone; read the tree again')
    return acc, Atspi


def act(node_id: str, action: str, text: str | None = None, expect: dict | None = None) -> dict:
    acc, Atspi = resolve(node_id)
    if expect:
        for key, getter in (('role', acc.get_role_name), ('name', acc.get_name)):
            if key in expect and (_call(getter, '') or '')[:120] != expect[key]:
                raise MirrorError('stale_node', f'{key} changed; read the tree again')
    try:
        if action == 'focus':
            comp = acc.get_component_iface()
            if comp is None or not comp.grab_focus():
                raise MirrorError('unsupported', 'element cannot take focus')
        elif action == 'set_text':
            editable = acc.get_editable_text_iface()
            if not isinstance(text, str) or editable is None:
                raise MirrorError('unsupported', 'set_text needs text and an editable element')
            if not editable.set_text_contents(text):
                raise MirrorError('unavailable', 'the application refused the text')
        else:
            iface = acc.get_action_iface()
            names = [iface.get_action_name(i) for i in range(iface.get_n_actions())] if iface else []
            wanted = ('click', 'press', 'activate', 'jump') if action == 'click' else (action,)
            index = next((names.index(w) for w in wanted if w in names), 0 if action == 'click' and names else None)
            if index is None:
                raise MirrorError('unsupported', f'element actions are {names}')
            iface.do_action(index)
    except MirrorError:
        raise
    except Exception as exc:  # GLib.Error
        raise MirrorError('unavailable', str(exc)[:300]) from None
    return {'ok': True, 'node': node_id, 'action': action}
