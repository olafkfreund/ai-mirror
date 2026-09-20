"""Windows whose contents must never reach a capture.

Seeded from omarchy-hermes-companion (MIT, Philippe Sthely),
daemon/perception.py, which solves the same problem for an always-on
screen-watcher. Its lists are a good floor; the rectangle logic here is not
its, because it only ever captures the focused window and `screenshot` takes a
region or a whole output.

**This is a heuristic.** It matches on window class and title, so it misses
things and it misfires. Nothing here makes a screen safe to photograph.
"""
from __future__ import annotations

import re

# (category, pattern). The category is what a refusal is allowed to say. The
# pattern is never reported: on this desktop window titles carry an inbox
# count, an email address and what is being watched, so quoting the thing we
# refused would leak it.
#
# Class and title are both tested because neither alone is enough. Measured
# here, a Gmail window reports class `chrome-<extension id>-Profile_4`, which
# identifies nothing; `pinentry` and `gcr-prompter` have generic titles and are
# identified only by class.
SENSITIVE = (
    ('a password manager',
     r'1password|bitwarden|keepass|keepassxc|proton.?pass|gnome-keyring|seahorse'),
    ('a credential prompt',
     r'polkit|pinentry|gcr-prompter|kwalletd|hyprlock|omarchy-lock|swaylock'),
    ('a private browsing window',
     r'private browsing|incognito|inprivate|private window|navigation priv'),
    ('a credential or one-time code',
     r'password|passcode|2fa|one-time|\botp\b'),
    ('a banking or payment page',
     r'\bbank\b|banque|revolut|paypal|stripe dashboard|credit card|carte bancaire'),
)


def kind(cls: str, title: str) -> str | None:
    """What kind of private thing this window is, or None.

    Returns a category from SENSITIVE and never the text it matched on.
    """
    haystack = f'{cls}\n{title}'
    for category, pattern in SENSITIVE:
        if re.search(pattern, haystack, re.I):
            return category
    return None


def covering(rect, windows, visible) -> list[dict]:
    """Windows from `windows` that lie inside `rect` and are on screen.

    `rect` is (x, y, w, h) in global layout pixels. The unit is the rectangle,
    not the focused window: `screenshot` takes a region or a whole output, so a
    password manager BESIDE the thing being captured is inside the frame and is
    exactly the case worth catching.

    Pure, so it can be tested without a compositor.
    """
    x, y, w, h = rect
    found = []
    for win in windows:
        if win.get('workspace') is not None and str(win['workspace']) not in visible:
            continue
        try:
            wx, wy = win['at']
            ww, wh = win['size']
        except (KeyError, TypeError, ValueError):
            continue
        if wx < x + w and x < wx + ww and wy < y + h and y < wy + wh:
            found.append(win)
    return found


def refuse(rect, windows, visible) -> str | None:
    """Why this rectangle must not be captured, or None."""
    for win in covering(rect, windows, visible):
        found = kind(str(win.get('class') or ''), str(win.get('title') or ''))
        if found:
            return (f'{found} is visible in that area, so nothing was captured. Capture a '
                    'specific region that excludes it, or ask the user to close it. This '
                    'matches on window class and title, so it misses things and it misfires.')
    return None
