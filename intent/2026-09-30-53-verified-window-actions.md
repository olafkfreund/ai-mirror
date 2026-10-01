---
status: approved
issue: 53
author: olafkfreund
---

# Intent: window says whether the action happened

## Problem

`window` returns `ok` when Hyprland accepted the dispatcher, not when the
window changed. Those are different facts: AGENTS.md already records that
`hl.dsp.window.close` can match nothing and still answer `ok`. An agent is
told it closed, moved, focused or resized a window when nothing happened, and
builds its next step on that. This is #8 again, for window operations: the
compositor would have told us, and we did not ask.

Two smaller problems make it worse:

- `float` is a toggle. An agent that is unsure whether the first call worked
  and retries turns floating back off. What the agent wants is a state
  ("floating"), not a flip.
- Pixel-resizing a tiled window cannot work, but it is sent anyway and
  reported as `ok`.

`windows` also returns no `pid`, so nothing can tell whether an address still
belongs to the window the agent looked at.

## Proposed outcome

- `window` reports what the compositor shows after the action: whether the
  window reached the requested state, and what it looked like before and
  after. An action that did not take effect is an error, not `ok`.
- Asking for a state that already holds sends nothing and says so.
- `float` can be told the state to reach, so retrying is safe.
- Resizing a tiled window is refused, with a message telling the agent not to
  retry.
- `windows` includes each window's `pid`.

## Affected users and systems

- Agents using the `window` MCP tool or `ai-mirror window`: a richer result
  and a new failure mode where they got a false `ok` before.
- `src/ai_mirror/api.py`, `host.py`, `mcp.py` (tool schema), `cli.py`, tests,
  `docs/usage.md`.
- No change to the ownership gate, the helper or the plugin.

## Constraints

- `window` stays a mutating operation behind the owner + generation gate.
- No free-form string reaches `hyprctl dispatch`. The new `float` argument is
  a bool, validated like everything else in `host.window_dispatch`.
- Tests cannot reach the desktop: the check reads through `host.windows()`,
  which tests stub. Reads stay unguarded, as now.
- The existing `float` call with no state keeps toggling, so current callers
  do not break.
- No new dependencies. Poll with what `wait.py` already does.

## Open questions

1. How long to wait for the state before calling it unverified? omapilot uses
   30×50 ms (1.5 s). Proposed: the same by default, overridable with
   `timeout` as `wait` is. **Decided: as proposed.**
2. Enforce the address + pid match (refuse if the pid at the address changed)
   now, or only report `pid`? Proposed: only report it until address reuse is
   actually seen. **Decided: as proposed.**
