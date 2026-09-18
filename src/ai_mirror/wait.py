"""Bounded confirmation that a prerequisite holds, before acting on it.

`input` reports that a keystroke was delivered, not that anything resulted from
it. A caller that assumes otherwise sends its next action into whatever happens
to have focus -- which is how a stray Return once queued a package removal into
a user's NixOS configuration.

This polls Hyprland's own state rather than subscribing to its event socket.
Every prerequisite here is already a state query costing about 10 ms, and a
prerequisite that *already holds* produces no event at all, so an event-shaped
design would wait out the whole timeout on the commonest case.

Three results, and keeping them apart is the point:

  confirmed      the prerequisite held
  not_confirmed  it did not hold before the deadline -- NOT that the action
                 failed. It may yet land. Retrying on this can toggle shut a
                 panel that had just opened.
  unavailable    the state could not be read at all, which is a different fact
                 from having looked and found nothing.
"""
from __future__ import annotations

import json
import time

DEFAULT_TIMEOUT = 3.0
MAX_TIMEOUT = 30.0
INTERVAL = 0.05


def _layers(value: str) -> bool:
    """Layer surfaces nest under monitor -> levels -> [{namespace}]."""
    from . import host
    data = json.loads(host.ctl('layers', '-j'))
    return any(layer.get('namespace') == value
               for monitor in data.values()
               for level in monitor.get('levels', {}).values()
               for layer in level)


def _clients() -> list[dict]:
    from . import host
    return json.loads(host.ctl('clients', '-j'))


def _window_class(value: str) -> bool:
    return any(c.get('class') == value for c in _clients())


def _window_title(value: str) -> bool:
    """Substring, because titles carry unread counts and document names."""
    return any(value in (c.get('title') or '') for c in _clients())


def _workspace(value) -> bool:
    from . import host
    active = json.loads(host.ctl('activeworkspace', '-j'))
    return str(active.get('id')) == str(value)


def _monitor(value: str) -> bool:
    from . import host
    return any(m['name'] == value and m['focused'] for m in host.monitors())


def _layout(value: str) -> bool:
    """Every keyboard, not any: typing goes through whichever is focused, and
    a caller asking this wants to know it cannot be typing in the wrong one."""
    from . import host
    boards = json.loads(host.ctl('devices', '-j')).get('keyboards', [])
    return bool(boards) and all(k.get('active_keymap') == value for k in boards)


PREDICATES = {
    'layer': _layers,
    'window_class': _window_class,
    'window_title': _window_title,
    'workspace': _workspace,
    'monitor': _monitor,
    'layout': _layout,
}


def until(args: dict | None = None) -> dict:
    """Poll one predicate until it holds, or the deadline passes."""
    args = args or {}
    named = [k for k in PREDICATES if args.get(k) not in (None, '')]
    if len(named) != 1:
        raise ValueError(
            'wait takes exactly one of ' + ', '.join(sorted(PREDICATES))
            + (f'; got {sorted(named)}' if named else '; got none'))

    name = named[0]
    check, value = PREDICATES[name], args[name]
    absent = bool(args.get('absent'))
    timeout = min(float(args.get('timeout') or DEFAULT_TIMEOUT), MAX_TIMEOUT)

    started, polls = time.monotonic(), 0
    while True:
        polls += 1
        try:
            held = check(value)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            # "could not look" must not be reported as "looked and it was not
            # there": a caller that conflates them acts on absent evidence.
            return {'result': 'unavailable', 'polls': polls,
                    'reason': f'{type(exc).__name__}: {exc}'.strip()[:200],
                    'waited_ms': round((time.monotonic() - started) * 1000)}
        if held is not absent:
            return {'result': 'confirmed', 'polls': polls, 'predicate': name,
                    'waited_ms': round((time.monotonic() - started) * 1000)}
        if time.monotonic() - started >= timeout:
            return {'result': 'not_confirmed', 'polls': polls,
                    'predicate': name,
                    'waited_ms': round((time.monotonic() - started) * 1000)}
        time.sleep(INTERVAL)
