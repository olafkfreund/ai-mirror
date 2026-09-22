---
status: draft
issue: 30
intent: intent/2026-09-22-30-live-test-findings.md
---

# Spec: what ai-mirror says it did, and what it did

## Design

Nine fixes, separable per issue, in one branch. Three carry the intent's open
questions; they are answered here, with the measurement each answer rests on.

### 1. A refused batch says how much it delivered (#30)

`run_batch` (`control.py:458`) keeps its per-line recheck — that is #24's
guarantee and removing it would trade a truthfulness bug for a safety one.
What changes is what it says when it stops.

`encode()` (`input.py:81`) gains a parallel list of action indices, one per
emitted line, so a line count can be expressed in the caller's own terms.
`run_batch` counts lines handed to the helper and, on a mid-batch refusal,
raises a `MirrorError` carrying `delivered` (lines), `of` (total),
`actions_completed` and `actions_total`, with a message in the form:

    partial: 9 of 14 lines delivered (actions 1-2 of 3 completed), then focus
    changed to 0x...; the rest was not sent and held keys were released.

`MirrorError` gains an optional `details` dict so the code and these counts
survive into both surfaces; `cli.py` and `mcp.py` render it inside the existing
`{"error": {...}}` envelope. When nothing was delivered the wording is
unchanged, because "input was NOT sent" is then true.

**Answer to open question 1:** report the prefix, do not attempt atomicity. A
16-action batch cannot be made atomic against a person at the keyboard, and
checking once before the batch would reintroduce the bug #24 closed.

### 2. The keyboard-target guard stops asserting what Hyprland cannot tell it (#29)

Measured on razer today: `hyprctl -j layers` on Hyprland 0.56.0 returns only
`address, alpha, h, namespace, pid, w, x, y` per surface. There is no
keyboard-interactivity field, and `activewindow` keeps naming the window
underneath while an overlay holds the keyboard. So no query answers "who has
the keyboard", and `_require_layer`'s `focused is None` precondition can never
hold for these overlays — the supported path is unreachable by construction.

Two changes, both in `control.py`:

- `_require_layer` drops the `focused is None` requirement and keeps the rival
  check it already computes: the named surface must be mapped with no other
  surface at its level or above, on any monitor. A still-focused window no
  longer refuses the call; it is named in the result note instead —
  "delivered to surface nixi (0x...); window 0x... also holds focus, so if the
  surface does not take the keyboard these keys land in that window."
- `_require_focus` gains the converse: when a surface that was not mapped at
  the moment control was granted is now mapped at level >= 2, typing at a
  *window* is refused and names it. The baseline set is snapshotted by
  `set_owner` when the grant is made (the shell's always-present surfaces,
  here `omarchy-background` and `omarchy-bar`), and recorded in the control
  state file, so "new surface since you took control" is a fact rather than a
  namespace allowlist that rots.

**Answer to open question 2:** yes, refuse the window path while an unexpected
keyboard-capable surface is up. The cost is that a notification layer can
block typing until it goes, which is the behaviour `_require_layer`'s rival
check already has and which the error tells the caller how to resolve.

### 3. A focus mismatch gets its own code (#31)

New code `wrong_target` for "that is not the focused window / not the surface
that can be typed into", leaving `stale_generation` for an ownership or
generation change. Raised from `_require_focus` and both `_require_layer`
refusals. The MCP tool descriptions in `mcp.py`, the `index.py` gotchas entry
and `docs/usage.md` are updated together, since the current wording is what
tells an agent to stop.

### 4. `doctor` checks the compositor (#32)

`doctor` gains a reachability probe — the same `host.focused_address()` path
every other subcommand depends on — and reports
`{"ok": false, "missing": [...], "compositor": "HYPRLAND_INSTANCE_SIGNATURE not set"}`,
naming the three variables a non-login shell lacks. `demo/rz` is referenced
from the message as the worked example.

### 5. `content` means content (#33)

`a11y.py:215` computes `deep` from `level >= CONTENT_DEPTH` alone, so a tree of
anonymous `grouping`s reports `content: true`. It becomes: a node at level >=
CONTENT_DEPTH that has a non-empty name, or actions, or text. The `NO_CONTENT`
note is extended for the case where deep nodes exist but none are actionable,
naming the app and pointing at `screenshot`. (The depth jumps reported in #33
are the deliberate `QUIET_ROLES` filter at `a11y.py:224`; no change there.)

### 6. A request is attributed to whoever made it (#34)

`mcp.py:189` passes `by='agent'`; `cli.py` passes nothing, so `set_owner`
defaults to `'human'` and an agent asking over ssh is announced to the person
as a human. `ai-mirror control agent` from the CLI passes `by='agent'`;
`confirm`/`deny`, which only the person at the desktop can issue, keep
`'human'`.

### 7. `--region` accepts what the MCP tool hands out (#35)

`cli.py` parses both `x,y,w,h` and `[x,y,w,h]`, and its error names the
expected form.

### 8. `set_text` tells the caller which of two things went wrong (#36)

`a11y.py:343` splits into: missing/!str `text` -> "set_text needs text";
missing EditableText interface -> "this element does not expose AT-SPI
EditableText (Chromium reports the editable state without the interface); use
`focus` on it and send keystrokes with `input`". Measured: that fallback drove
a Chrome form correctly in the same session.

### 9. The middle button is documented as unavailable (#37)

Measured: `left`, `right`, `back` and `forward` all work; `middle` is acked and
does nothing in Chrome (tab close, link in new tab) or GTK (primary paste),
and `ai_mirror_input.c` sends every button through one identical
`zwlr_virtual_pointer_v1_button` call. The loss is downstream of this codebase.

**Answer to open question 3:** document, do not chase. A gotchas entry and a
line in `docs/usage.md`; #37 stays open for the compositor-side investigation.
No result is marked `ok: false`, because ai-mirror cannot observe the loss.

## Alternatives rejected

- **Check focus once, then send the batch atomically** (#30): reintroduces the
  window #24 closed, in which the desktop moves mid-batch and input lands
  somewhere else. Rejected on safety.
- **Silently cancel and report success for the prefix** (#30): swaps a false
  negative for a false positive. Rejected.
- **A namespace allowlist of keyboard-capable layers** (#29): fragile against
  every new plugin, and wrong the first time a panel changes its
  interactivity. The grant-time baseline needs no such list.
- **Refuse the window path whenever any layer above the bar is mapped**
  (#29): equivalent in the common case but blocks typing under surfaces that
  were already there when control was granted, including the shell's own.
- **Patch Hyprland or wait for a protocol field** (#29): out of scope here;
  the baseline approach works on 0.56 as shipped.
- **Auto-fallback from `set_text` to focus+type** (#36): would deliver
  keystrokes from a call the caller believes is a property write, and would
  need the input guard's window argument, which `a11y_act` does not take.
- **Marking middle-button clicks as failed** (#37): ai-mirror cannot observe
  whether they landed; claiming failure would be the same class of bug as #30.

## Risks

- **razer, p620**: the #29 baseline check will refuse window-addressed input
  while a notification or launcher is mapped. Agents that type through
  transient surfaces today will start seeing `wrong_target`. This is the
  intended behaviour but it is a behaviour change for every caller.
- **Stale baseline**: if the shell maps a surface after the grant that is
  always present thereafter (a bar restart), every subsequent window-addressed
  call is refused until control is re-taken. Mitigation: the refusal names the
  surface and the state file records when the baseline was taken.
- **#30's counts**: `delivered` is lines handed to the helper and acked, which
  is delivery to the compositor, not acceptance by the application. The
  message must not imply more than that — the existing "delivered is not
  accepted" wording is reused.
- **#33**: tightening `content` will flip some currently-`true` results to
  `false`. That is the point, but any caller keying on it sees a change.

## Verification

- Unit: `encode()` action-index mapping; `run_batch` against a fake helper that
  fails on the nth line, asserting `delivered`/`actions_completed` and that the
  message does not say "NOT sent" when n > 0.
- Unit: `_require_focus` / `_require_layer` against recorded `layers` and
  `activewindow` fixtures, including the razer nixi case, asserting
  `wrong_target` and the baseline behaviour.
- Unit: `doctor` with the compositor env stripped; `content` on a recorded
  GTK4 tree and a recorded Chrome tree; region parsing of both forms.
- Live on razer, with control granted: reproduce #30's cat-window case and
  assert the error names a partial delivery matching the file's contents;
  open nixi and type into the surface (must now succeed) and at the window
  behind it (must now refuse, naming nixi); `doctor` over a bare ssh shell.
- The screencast in `demo/` re-recorded after the change, as a whole-system
  check that nothing in the ordinary path regressed.
