---
status: draft
issue: 74
author: olafkfreund
---

# Intent: the live smoke test passes on this host again

## Problem

`tests/smoke.py` is the live check that ai-mirror works on the real desktop.
On master (3.0.0) it fails twice before it reaches the part that drives the
desktop. That part, run on its own, passes: launch, windows, focus, frame
input, Unicode typing, clipboard, kill switch.

1. **The index is over its byte budget.** The default `index` payload is
   25,266 bytes, and the budget is 22,000 (spec #3: "an index too expensive to
   read at the start of a session is an index that stops being read").
   About 15.7 KB of it is `gotchas.md`, which grew with the measured rows
   from #65 and #70. The rest is this host's keys (3.7 KB) and plugins
   (4.8 KB). The unit test stays under budget because it uses a made-up host.
2. **`check_wait` relies on a plugin this host has turned off.** It presses
   Super+Alt+N and waits for `nixarchy-pkg-menu`. But `nixarchy.pkg` is
   not enabled here, so the panel never opens and the check reports a bug
   in `wait` that doesn't exist.

## Proposed outcome

- `tests/smoke.py` passes end to end on this host.
- The default index fits a budget that is stated and justified. Either it
  shrinks back under 22,000, or the budget changes and the reason is
  written down.
- `check_wait` exercises a panel that this host actually has. If no
  usable panel exists, it says so plainly ("SKIP: ... because ...") instead
  of failing with a false bug report.

## Affected users and systems

Anyone running the smoke test. Agents that read `index` at the start of a
session, which is the budget's whole purpose. No runtime behaviour of the
MCP tools changes.

## Constraints

- The measured table stays reachable. It is how an agent knows what works
  where.
- Tests still cannot reach the desktop. Only `smoke.py` drives it, and it
  takes control the way it does today.
- The unit test and the smoke test use the same budget.

## Open questions

1. **Index budget.** I propose **(b)**.
   - **(a)** Raise the budget to 26,000. One line, but it grows again with
     every measurement.
   - **(b)** Move the measured per-app table out of the default payload. It
     would still be served by `index --section gotchas` and `a11y`, with a
     one-line pointer left in the default. That frees about 2.5 KB. Then
     trim the longest prose sections ("Typing into a menu, panel or
     launcher" at 2.7 KB, "Chrome ignores the middle mouse button" at 1 KB)
     to get under 22,000 with room to spare.
2. **`check_wait`'s panel.** I propose **(b)**.
   - **(a)** Hard-code another plugin's panel.
   - **(b)** Pick the first enabled plugin that `index` joins to a key and
     that opens a layer, and skip with a reason if there is none. That
     keeps the check host-derived, like the rest of the index.
