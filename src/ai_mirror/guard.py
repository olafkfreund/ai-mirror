"""Stop the test suite reaching the human's desktop.

Off in normal use. The tests arm it, and the seams that change the world
outside this process refuse while it is armed -- so a forgotten stub is a test
failure rather than a write to somebody's live session. That has happened
twice: #12's control gate, where ControlTests already takes control and would
have written org.a11y.Status on the real bus, and 584d8ee before it. Both were
caught by a person reading a diff, which does not scale to a third.

Reads are deliberately NOT guarded. A window query or an accessibility walk
observes without disturbing anything, and index.nav()'s enable=False read has
to keep working; guarding those would put a mock in front of every harmless
call and the cost would land on every future test.
"""
from __future__ import annotations

_armed = False


class Blocked(Exception):
    """A guarded seam was reached while the guard was armed.

    Deliberately not a RuntimeError. control.run_batch catches RuntimeError and
    turns it into a MirrorError (control.py), which would bury the message that
    says which seam was hit and what to stub -- the only part of this worth
    having.
    """


def arm() -> None:
    """Refuse the side-effecting seams from here on. The test base class calls this."""
    global _armed
    _armed = True


def disarm() -> None:
    """Let a test through to a real seam. One line, and it should stay rare."""
    global _armed
    _armed = False


def armed() -> bool:
    return _armed


def check(seam: str, stub: str) -> None:
    """Raise if `seam` would change the real desktop right now.

    `stub` names what to patch, because a failure whose message does not say
    that just moves the puzzle from review time to debug time.
    """
    if _armed:
        raise Blocked(f'{seam} would change the real desktop, and the test suite '
                      f'must not. Stub {stub}, or call guard.disarm() in this '
                      f'test if it genuinely needs the real thing.')
