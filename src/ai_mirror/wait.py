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
import math
import time

DEFAULT_TIMEOUT = 3.0
MAX_TIMEOUT = 30.0
INTERVAL = 0.05


def _ask(request: str, budget: float):
    """One hyprctl query, bounded by what is left of the caller's deadline."""
    from . import host
    return json.loads(host.ctl(request, '-j', timeout=budget))


def _layers(value: str, budget: float) -> bool:
    """Layer surfaces nest under monitor -> levels -> [{namespace}].

    A monitor entry without `levels`, or a layer without `namespace`, means the
    response is not the shape this understands. Treating that as "the layer is
    absent" would report confident absence from a reply we failed to parse, so
    it raises and becomes `unavailable` instead.
    """
    data = _ask('layers', budget)
    if not isinstance(data, dict) or not data:
        raise ValueError('layers: unexpected shape')
    found = False
    for monitor in data.values():
        levels = monitor['levels']
        for level in levels.values():
            for layer in level:
                found = found or layer['namespace'] == value
    return found


def _clients(budget: float) -> list[dict]:
    data = _ask('clients', budget)
    if not isinstance(data, list):
        raise ValueError('clients: unexpected shape')
    return data


def _window_class(value: str, budget: float) -> bool:
    return any(c['class'] == value for c in _clients(budget))


def _window_title(value: str, budget: float) -> bool:
    """Substring, because titles carry unread counts and document names. It
    matches any window anywhere, including one on another workspace."""
    return any(value in c['title'] for c in _clients(budget))


def _workspace(value, budget: float) -> bool:
    """The focused monitor's active workspace, compared as text so 8 and "8"
    agree. Workspace names and `special:` overlays are out of scope: this
    answers "is that id active", not "is it visible"."""
    active = _ask('activeworkspace', budget)
    return str(active['id']) == str(value)


def _monitor(value: str, budget: float) -> bool:
    from . import host
    return any(m['name'] == value and m['focused'] for m in host.monitors())


def _layout(value: str, budget: float) -> bool:
    """Every keyboard, and never vacuously true for none of them.

    Conservative on purpose: this cannot tell which device a future keystroke
    will travel through, and ai-mirror's own virtual keyboard starts on a US
    keymap regardless of what the physical ones report. On a host with mixed
    layouts this will refuse rather than guess.
    """
    boards = _ask('devices', budget)['keyboards']
    return bool(boards) and all(k['active_keymap'] == value for k in boards)


PREDICATES = {
    'layer': _layers,
    'window_class': _window_class,
    'window_title': _window_title,
    'workspace': _workspace,
    'monitor': _monitor,
    'layout': _layout,
}


def _timeout(value) -> float:
    """A finite, non-negative deadline, clamped.

    `nan` is the dangerous one: `min(nan, MAX)` is `nan` and nothing is ever
    `>= nan`, so an unvalidated nan would poll for ever. Zero is honoured as
    zero -- one immediate check and an answer -- rather than being swallowed by
    a falsy default, because "look once" is a reasonable thing to ask for.
    """
    if value is None:
        return DEFAULT_TIMEOUT
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'timeout must be a number, got {value!r}') from None
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f'timeout must be finite and >= 0, got {value!r}')
    return min(seconds, MAX_TIMEOUT)


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
    timeout = _timeout(args.get('timeout'))

    started, polls = time.monotonic(), 0

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    while True:
        polls += 1
        try:
            # Each probe gets only what is left of the caller's budget.
            # host.ctl otherwise allows itself ten seconds, so one slow query
            # could blow a 0.1 s deadline by two orders of magnitude.
            held = check(value, max(timeout - (time.monotonic() - started), 0.1))
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            # "could not look" must not be reported as "looked and it was not
            # there": a caller that conflates them acts on absent evidence.
            return {'result': 'unavailable', 'polls': polls, 'predicate': name,
                    'reason': f'{type(exc).__name__}: {exc}'.strip()[:200],
                    'waited_ms': elapsed_ms()}
        if held is not absent:
            return {'result': 'confirmed', 'polls': polls, 'predicate': name,
                    'waited_ms': elapsed_ms()}
        left = timeout - (time.monotonic() - started)
        if left <= 0:
            return {'result': 'not_confirmed', 'polls': polls,
                    'predicate': name, 'waited_ms': elapsed_ms()}
        time.sleep(min(INTERVAL, left))
