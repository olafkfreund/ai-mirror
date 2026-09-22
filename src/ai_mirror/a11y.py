"""AT-SPI accessibility tree: find controls by role/name and act on them without pixels.

Needs PyGObject + the at-spi2-core typelib (the flake package provides both).
Node ids are child-index paths from the desktop ("app.child.child…"); act()
re-resolves the path and refuses if role or name changed since it was read.
"""
from __future__ import annotations

import subprocess

from . import guard
from . import privacy
from .control import MirrorError

STATES = ('enabled', 'focused', 'focusable', 'editable', 'checked', 'selected',
          'expanded', 'collapsed', 'pressed', 'sensitive', 'multi-line')
QUIET_ROLES = ('filler', 'panel', 'section', 'redundant object', 'unknown')
VISIT_CAP = 20000
A11Y_STATUS = ('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Status')
A11Y_PROPS = ('IsEnabled', 'ScreenReaderEnabled')
_enabled = False  # enable_bus is worth doing once, not once per walk
_restore: dict[str, bool] = {}  # what a bare read switched on, for teardown


def _atspi():
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
    except (ImportError, ValueError) as exc:
        raise MirrorError('unavailable', f'AT-SPI bindings missing ({exc}); use the flake package') from None
    return Atspi


def _busctl(verb: str, prop: str, *value: str) -> subprocess.CompletedProcess:
    if verb == 'set-property':
        # The guard belongs on the innermost real call -- the one a test stubs.
        # Above it, on set_bus_property, a correctly stubbed test is blocked
        # too. Reads are not guarded, per the spec.
        guard.check('a11y._busctl set-property', 'a11y._busctl')
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


def ensure_enabled() -> None:
    """Enable the bus once per process, remembering what we switched on.

    Control puts back what control switched on. A bare read has no such
    lifecycle, so without the record an `a11y-find` would enable the bus for
    good and quietly defeat the gating. On failure the flag stays down, so the
    next walk retries.
    """
    global _enabled
    if _enabled:
        return
    before = enable_bus()
    _enabled = True
    _restore.update({prop: was for prop, was in before.items() if was is False})


def release_bus() -> None:
    """Put back what a bare read switched on. Idempotent; never raises.

    Skipped while an agent holds control: the grant switched the bus on for its
    own tenure and `control off` is what ends that.
    """
    from .control import read_state
    if not _restore or read_state().get('owner') == 'agent':
        return
    for prop in list(_restore):
        try:
            set_bus_property(prop, False)
        except MirrorError:
            pass
        _restore.pop(prop, None)


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
    # Control already enables this when the agent takes over; this is the
    # fallback for a bare CLI read, and it is worth one subprocess per process
    # rather than one per walk.
    if enable:
        ensure_enabled()
    desktop = Atspi.get_desktop(0)
    visited = 0
    for index in range(_call(desktop.get_child_count, 0)):
        root = _call(lambda: desktop.get_child_at_index(index))
        if root is None:
            continue
        root_name = _call(root.get_name, '') or ''
        if app and app.lower() not in root_name.lower():
            continue
        # #20: an application node's name plays the part of a window class, so
        # 1Password or gcr-prompter is refused whole. A frame's name plays the
        # part of a title, and is checked per frame below -- one Google Chrome
        # node carries a frame per window, so refusing the application because
        # one window is a bank would remove every Chrome window from the tree.
        app_withheld = privacy.kind(root_name, '')
        stack = [(str(index), root, 0)]
        while stack:
            node_id, acc, level = stack.pop()
            visited += 1
            if visited > VISIT_CAP:
                return
            withheld = app_withheld if level == 0 else None
            if withheld is None and level == 1:
                withheld = privacy.kind(root_name, _call(acc.get_name, '') or '')
            yield node_id, acc, level, Atspi, withheld
            if withheld:
                continue  # yielded as a fact, never descended into
            if level < depth:
                children = []
                for i in range(_call(acc.get_child_count, 0)):
                    child = _call(lambda i=i: acc.get_child_at_index(i))
                    if child is not None and _showing(child, Atspi):
                        children.append((f'{node_id}.{i}', child, level + 1))
                stack.extend(reversed(children))


CONTENT_DEPTH = 2  # an app holds a frame holds content; depth 2 is the first real node


def _actionable(row: dict, level: int) -> bool:
    """Whether this node is something a caller could find or act on.

    Depth alone used to answer this (#33), which made a tree of anonymous
    `grouping` nodes -- what GTK4 exposes for gnome-text-editor: 24 nodes, not
    one of them named -- report `content: true`. A caller then trusts the tree
    and finds nothing to target. A node counts when it carries a name to match
    on, an action to invoke, or text to read.
    """
    return level >= CONTENT_DEPTH and bool(row.get('name') or row.get('actions') or row.get('text'))


NOTHING_ACTIONABLE = ('this desktop exposed a tree with no named or actionable nodes under any '
                      'window: nothing here can be matched by name or acted on, so use screenshot. '
                      'GTK4 applications often expose only anonymous groupings this way.')
NO_CONTENT = ('this desktop exposed no accessibility content: every node was an '
              'application or a window frame, with no controls under them. An empty '
              'result here means the tree is unavailable, NOT that the screen is '
              'empty -- use screenshot instead. Chromium and Electron only expose '
              'content when launched with --force-renderer-accessibility.')


def _coverage(visited: int, deep: bool, truncated: bool, actionable: bool | None = None) -> dict:
    """What the walk saw, so an empty result is not read as an empty screen.

    The counts come from the traversal that already runs -- no second walk and
    no extra AT-SPI calls. `content` reports whether anything actionable was
    found, not merely whether the walk went deep (#33); `deep` still separates
    "only applications and frames" from "nodes underneath, but none usable",
    because those two want different advice.
    """
    if actionable is None:
        actionable = deep
    coverage = {'visited': visited, 'content': actionable}
    if not actionable and not truncated:
        coverage['note'] = NOTHING_ACTIONABLE if deep else NO_CONTENT
    return coverage


def tree(app: str | None = None, depth: int = 12, max_nodes: int = 400,
         enable: bool = True) -> dict:
    nodes, truncated, visited, deep, actionable = [], False, 0, False, False
    for node_id, acc, level, Atspi, withheld in _walk(app, depth, enable):
        visited += 1
        deep = deep or level >= CONTENT_DEPTH
        if withheld:
            # The fact, never the name: a frame's name is the sensitive part.
            # _node() is not called at all, so no text or bounds are read.
            nodes.append({'id': node_id, 'role': _call(acc.get_role_name, '') or '',
                          'withheld': withheld, 'depth': level})
            continue
        row = _node(acc, node_id, Atspi)
        actionable = actionable or _actionable(row, level)
        if level and not row['name'] and row['role'] in QUIET_ROLES and 'text' not in row:
            continue
        if len(nodes) >= max_nodes:
            truncated = True
            break
        row['depth'] = level
        nodes.append(row)
    return {'nodes': nodes, 'truncated': truncated,
            **_coverage(visited, deep, truncated, actionable)}


def find(name: str | None = None, role: str | None = None, app: str | None = None, limit: int = 20) -> dict:
    if not name and not role:
        raise ValueError('give name and/or role')
    matches, visited, deep = [], 0, False
    kept_out: list[str] = []
    # Per application, so an empty result can say which ones had nothing to
    # match rather than implying the element is absent. Keyed by the walk's own
    # root index; one get_name per application, not per node.
    apps: dict[str, list] = {}
    for node_id, acc, level, Atspi, withheld in _walk(app, 64):
        visited += 1
        deep = deep or level >= CONTENT_DEPTH
        if withheld:
            kept_out.append(withheld)
            continue
        root = node_id.split('.')[0]
        if level == 0:
            apps[root] = [(_call(acc.get_name, '') or '?')[:40], False]
        elif level >= CONTENT_DEPTH and root in apps:
            apps[root][1] = True
        if name and name.lower() not in (_call(acc.get_name, '') or '').lower():
            continue
        if role and role.lower() != (_call(acc.get_role_name, '') or '').lower():
            continue
        matches.append(_node(acc, node_id, Atspi))
        if len(matches) >= limit:
            break
    coverage = _coverage(visited, deep, False)
    if kept_out:
        coverage['withheld'] = len(kept_out)
    if matches:
        # A match proves the tree is usable, so the no-content note must not
        # fire. It could: this loop breaks at `limit`, so `deep` only reflects
        # what was walked before the break -- `--role frame --limit 2` stops at
        # depth 1 and looked like a desktop exposing nothing.
        coverage.pop('note', None)
    elif kept_out:
        # Different from "this desktop exposes nothing" (#18): here something
        # WAS there and was deliberately not looked at, which changes what an
        # agent should do next.
        kinds = ", ".join(sorted(set(kept_out)))
        coverage['note'] = (f'no match, and {len(kept_out)} window(s) were not looked at '
                            f'because of what they are ({kinds}). The element may well be '
                            'inside one of those. Ask the user to close it, or work from a '
                            'screenshot of a region that excludes it.')
    else:
        coverage.setdefault('note', _why_empty(apps))
    return {'nodes': matches, **coverage}


def _why_empty(apps: dict[str, list]) -> str:
    """Why a find came back empty, when the desktop as a whole has a tree.

    _coverage only speaks when NOTHING anywhere exposed content. The commoner
    case is a desktop where some applications do and the ones being asked about
    do not -- and there the bare empty list reads as "the element is not there",
    which is the wrong conclusion and the one #13 is about.
    """
    silent = [name for name, has in apps.values() if not has]
    if not silent:
        return ('no match, and every application walked did expose content, so '
                'the element is genuinely not there right now.')
    return (f'no match. Of {len(apps)} applications walked, {len(silent)} exposed no '
            f'content at all and so could not match anything: '
            f'{", ".join(sorted(silent))}. That is not the same as the element '
            f'being absent -- use screenshot for those. Chromium and Electron '
            f'expose content only when launched with '
            f'--force-renderer-accessibility (#13).')


def resolve(node_id: str):
    Atspi = _atspi()
    parts = node_id.split('.') if isinstance(node_id, str) else []
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError('node must be an id from a11y_tree or a11y_find')
    acc = Atspi.get_desktop(0)
    # #20: re-checked here, not only during the walk. Without this an id taken
    # a moment before a window became sensitive still resolves, and act() would
    # reach inside it. Part 0 is the application, part 1 its window.
    app_name = ''
    for depth, part in enumerate(parts):
        acc = _call(lambda: acc.get_child_at_index(int(part)))
        if acc is None:
            raise MirrorError('stale_node', 'the element is gone; read the tree again')
        if depth == 0:
            app_name = _call(acc.get_name, '') or ''
            refused = privacy.kind(app_name, '')
        elif depth == 1:
            refused = privacy.kind(app_name, _call(acc.get_name, '') or '')
        else:
            refused = None
        if refused:
            raise MirrorError('sensitive',
                              f'that element is inside {refused}, so it was not read '
                              'and cannot be acted on.')
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
            if not isinstance(text, str):
                raise MirrorError('unsupported', 'set_text needs text')
            editable = acc.get_editable_text_iface()
            if editable is None:
                # Chromium reports the `editable` state without implementing the
                # interface, so the old message blamed the caller's arguments for
                # something they could not fix by passing them again (#36).
                raise MirrorError('unsupported',
                                  'this element does not expose AT-SPI EditableText, so its text '
                                  'cannot be set directly (Chromium reports the editable state '
                                  'without the interface). Use a11y_act focus on it, then send '
                                  'keystrokes with input.')
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
