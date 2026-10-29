---
status: approved
issue: 77
author: olafkfreund
---

# Intent: check_wait leaves no window behind

## Problem

`tests/smoke.py` `check_wait` finds a panel by pressing each candidate plugin's
`opens_with` key and diffing `host.layers()`. Afterwards it hides the plugin
(`omarchy-shell shell hide`). If a key opens a **window** instead of a layer:
- nothing closes the window;
- focus moves to it, so the next candidate's key press lands in it.

The smoke run then types into a window it opened by accident, on the user's real
desktop. This is latent today, because every candidate on p620 is a shell panel,
but any plugin whose key launches an app triggers it.

Second, lower priority, from the same review: `sorted(new)[0]` can pick an
unrelated layer, such as a notification, that maps during the 5 s window.

## Proposed outcome

- After each candidate press, any window that wasn't there before the press is
  closed, and the loop carries on.
- A smoke run leaves the desktop's window set as it found it.

## Affected users and systems

- `tests/smoke.py` only (the live smoke run, executed by hand on p620).
- No server or package change, and nothing in CI (smoke needs a live desktop).

## Constraints

- Close only windows that are new since the snapshot taken just before that press.
  Never close a window that existed before.
- Close through the same API the smoke run already drives (`window` close), so the
  guard and control rules apply.
- Never type into a discovered window or panel.

## Open questions

- **The layer pick (part 2):** fix it now by preferring a new layer whose `pid` is the
  shell's, or leave it out? I propose leaving it out: no host shows it, and finding the
  shell's pid adds more than the bug costs. I'll note it on the issue and close #77
  with the window fix.
