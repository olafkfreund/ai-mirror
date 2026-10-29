---
status: draft
issue: 85
author: olafkfreund
---

# Intent: the audit never records a grant that did not happen

## Problem

`control._answer` writes `audit('confirmed', …)` at `src/ai_mirror/control.py:457`.
Only after that does it check that the Hyprland instance the grant would be
stamped with is running (`:471-473`). When that check fails, it raises
`bad_request`. The state stays `pending` and nothing is granted, but the
trail already says `confirmed`.

`audit` is the record a person reads to decide whether to trust an agent
(AGENTS.md, #44). A `confirmed` line that granted nothing is a false
record, and it surfaces in two places:

- **nixarchy#1505's `hyprland-ai-mirror` sandbox** confirms every 0.5 s
  while its Hyprland starts. A cold boot leaves about 40 `confirmed`
  lines for one grant.
- **The real desktop:** a human who answers the dialog while Hyprland is
  down or restarting gets a `confirmed` line and no grant.

## Proposed outcome

- A `confirmed` line in the audit means control was granted. Every line
  is written only once its outcome is certain.
- An answer that cannot grant still returns `bad_request` to the answerer,
  as today. The request stays pending and later lapses as `expired`, as
  today.
- `denied` is unaffected: a denial cannot fail that way.

## Affected users and systems

- `src/ai_mirror/control.py` (`_answer`) and its tests
  (`tests/test_audit_answerer.py` or `tests/test_invariants.py`).
- Anyone who reads `ai-mirror audit`.
- No change to the MCP tools, the CLI's arguments, the dialog, or the gate's
  decisions.

## Constraints

- **The gate's behaviour does not change.** The same answers grant, deny or
  fail, in the same state.
- **Tests cannot reach the desktop.** The test stubs the instance check,
  as the existing control tests do (`guard.arm()`).
- **The audit's line format is unchanged** for lines that are written.
- **`audit` stays CLI-only.** Nothing here touches `mcp.SPECS`
  (`tests/test_audit.py` asserts it).

## Open questions

1. **Should a failed confirm leave a trace?** A human who pressed `A`
   while Hyprland was restarting did answer, and nothing records it.
   Proposed: no new event. The answerer gets the error at the time, and the
   request's eventual `expired` line already shows that nobody's answer took
   effect. The alternative is a new `confirm_failed` event: more to read,
   and a new event kind for readers to learn.
