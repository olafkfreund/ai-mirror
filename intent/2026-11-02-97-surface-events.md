---
status: approved
issue: 97
author: olafkfreund
---

# Intent: the surface check sees a surface that left and came back between checks

## Problem

Before a window-addressed keystroke, `_refuse_new_surfaces` (`src/ai_mirror/control.py`)
compares `hyprctl layers` with the grant's baseline: what was mapped when control
was granted, shrunk whenever a check finds one gone (#39). It samples only at
those moments. A surface that unmaps and maps again between two checks is never
seen leaving, so it keeps counting as furniture for the rest of the grant
(`gotchas.md`: "a quick leave-and-return goes unseen"). That is the more
suspicious shape #39 names: a namespace that was part of the desktop, went, and
is back — possibly holding the keyboard over the target.

Since #95 the MCP server records Hyprland's `closelayer`/`openlayer` events
(with namespace) while its agent holds control, measured on p620 for the
Quickshell audio panel and the confirm dialog. The check does not use them.

## Proposed outcome

- In the MCP server, while its event reader is connected and recording this
  grant, a `closelayer` of a baseline namespace since the grant drops it from
  the furniture, exactly as if a check had sampled it gone. The next
  window-addressed keystroke with that surface up is refused with "went away
  and came back".
- Wherever events cannot vouch for the whole grant — the CLI, a disconnected
  reader, a ring that overflowed or reported a gap, a grant whose recording
  started late — the check behaves exactly as today. Events can only make it
  stricter, never weaker.
- `gotchas.md` says when the leave-and-return is now seen and when it still is
  not.

## Affected users and systems

- `src/ai_mirror/control.py` (the gate), `src/ai_mirror/events.py`, tests, `gotchas.md`.
- Agents driving p620 through MCP: some keystrokes refused today's sampling
  would have let through. No change for CLI users.
- Deployed via nixarchy edge → p620, as #95.

## Constraints

- This is the safety gate: never weaker on any path. A missing, partial or
  doubtful event record means "sample as today", never "trust the record".
- Events are what Hyprland reported (`gotchas.md`); a layer event is evidence of
  a surface change, not of who made it.
- No new tool, argument or dependency; `events` stays MCP-only (#95).
- The reader thread must not write the state file (#95 review: state belongs to
  the main thread); the check reads the recorder, it does not get pushed to.
- Tests cannot reach the desktop (`guard.arm()`); both paths need tests.

## Decisions (approved 2026-11-02)

1. Accept the stricter refusal; no namespace is exempt. After a shell restart
   seen in events, window-addressed input is refused until control is re-taken,
   as `gotchas.md` already says for a restart a check happens to sample.
2. A departure seen in events is written into `baseline_layers` /
   `baseline_departed` in the state file by the main thread at check time, so a
   later CLI call in the same grant is not weaker than the MCP call before it.
