---
status: approved
issue: 68
author: olafkfreund
---

# Intent: a key-up after its target closes does not fail the batch

## Problem

`run_batch` re-checks the typing target before every helper line (#24). That
is right for a key press: if focus moved, the keystroke must not land
somewhere else. It is wrong for one case. When a keystroke closes its own
target, the matching key-up arrives after the target has gone:

- **A layer:** Escape on a menu or panel. PR #52 (branch
  `fix/layer-release-input`) handles this and nothing more; its description
  keeps per-line validation for windows on purpose.
- **A window:** Enter that ends the program running in it. Reproduced live in
  `tests/smoke.py` `main()`, the `foot` window running `read`:

  ```text
  10  K 28 1   Enter down: read completes, sh exits, foot closes
  11  K 28 0   Enter up: refused
  wrong_target: partial: 10 of 11 lines delivered (actions 1-3 of 4 completed)
  ```

The text landed and the window closed, as asked. The caller is told it
failed. An agent that believes that retries, typing the line again into
whatever now has focus. This is #8's shape -- the result says something
other than what happened -- and the smoke test cannot pass while it stands.

## Proposed outcome

- A batch whose keystroke closes its own target, window or layer, completes
  and reports success, with every key it pressed released.
- Every press, every `T` text line, every pointer move and every new action is
  still checked against the target before it is sent, exactly as now.
- The success result tells the truth about where the keys went. Today's note
  says "`<window>`, which still had focus" or "the topmost surface on screen"
  (`control.py:820-826`), which is false once the target closed; the note says
  the target closed after the keystroke instead.
- `tests/smoke.py` `main()` passes end to end (once PR #67, which fixes the
  smoke test's #24 gaps, is merged into this branch).
- PR #52 is this issue's implementation; its layer-only rule widens to cover
  windows.

## Affected users and systems

- Agents using `input` with `window` (MCP and CLI).
- `src/ai_mirror/control.py` (`run_batch` and its result note),
  `tests/test_layer_typing.py` and window-case tests, `tests/smoke.py` (its #24
  gaps are fixed in PR #67, commit `6bea83a`).
- No change to the helper, the plugin, the confirm dialog or the ownership
  gate.

## Constraints

- **Generation + owner still gate every line.** The `read_state()` check above
  the target check stays untouched, so the kill switch still stops a batch
  mid-way (AGENTS.md: "`run_batch` re-reads the state before every helper
  line").
- Every failure path still sends `C` (release all).
- Only a *release* (`K <code> 0` / `B <code> 0`) whose **matching press** (same
  code) was sent earlier in the *same action*, after that action's target was
  validated, may skip the target check. A release cannot type text. #52 today
  exempts any release after a validated layer, matched or not
  (`control.py:775-799`); this narrows it.
- A target list that cannot be read is not evidence the target is gone; it
  must stay a refusal. `_require_target` cannot be reused for this as it
  stands: it turns a failed layer query into "no layers" (`control.py:724-727`),
  which fails closed when asking "is the target present" but would fail
  *open* when asking "is it gone". And for a window it never asks whether the
  window exists, only what has focus (`_require_focus`): when a window closes
  on a workspace with another window, focus moves there, which looks the same
  as losing focus. "Gone" has to come from `host.windows()` /
  `host.layers()` with their errors propagated.
- Tests cover: a window that closes on the press, a layer that closes, a target
  that still exists but lost focus (still refused), an unmatched release
  (still checked), and an unreadable target list (still refused).
- Tests cannot reach the desktop: the window case is tested with `host`
  stubbed, as `tests/test_layer_typing.py` does for layers.

## Open questions

1. When the target window **still exists but lost focus** (rather than
   closed), should its pending key-up be sent to whatever has focus, or should
   the batch stop there as now? #52 does not distinguish for layers.
   Proposed: exempt the release only when the target is **gone** (window
   closed, layer unmapped); if it still exists elsewhere, keep today's refusal.
   This is narrower than #52, and the helper's `C` releases the key on that
   path anyway.
   **Trade-off:** it does not cover a key-down that *opens* something -- a
   shortcut that maps a new window or panel before its key-up. The target
   still exists, so the key-up is refused and the batch reports a partial
   failure for a shortcut that worked, which is today's behaviour. The
   alternative, "release any key this action pressed, wherever focus is",
   covers that too, and sends nothing `C` would not have sent on the failure
   path; it is #52's current rule, made to require a matching press. Your
   call: narrow ("target gone") or broad ("matching press"). **Decided: as proposed (narrow, "target gone").**
2. Rewrite #52's layer rule to the same "target gone" test, or keep #52's
   broader layer rule and add the narrower window rule beside it? Proposed: one
   rule for both, "target gone", so there is a single behaviour to describe. **Decided: as proposed.**
