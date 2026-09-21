---
status: draft
issue: 24
intent: intent/2026-09-21-24-verified-input.md
---

# Spec: A keystroke should not land in a window nobody chose

## Design

`input` gains an optional `window` — a Hyprland address of the kind `windows`
already returns. When the batch contains **keyboard** actions, it is required.
Before every keyboard line, the focused address is compared against it, and a
mismatch aborts the batch.

The check goes in `run_batch` (`control.py:378`), in the loop that already
rechecks ownership before every line:

```python
for line in lines:
    state = read_state()
    if state.get('owner') != 'agent' or state.get('generation') != generation:
        helper.cancel()
        raise MirrorError('stale_generation', 'control changed during the batch')
    # new: the same question, asked about focus
```

That placement is the design, not a detail. The codebase already holds that an
invariant worth checking is worth rechecking **per action** rather than per
call, because a batch is not atomic and the desktop moves underneath it. Focus
is such an invariant and was simply missing from the list.

### Why an explicit address, rather than pinning whatever is focused

Pinning focus at the start of the batch is the obvious cheap answer and it does
not fix the reported failure. In the incident, the shell restarted and a
different panel took the place of the agent's **before** its next action. A
batch starting after that moment would have pinned the wrong window and
proceeded confidently.

Only the caller naming the window it means distinguishes "the thing I chose"
from "the thing that happens to be in front". That is the same shape as `frame`
for coordinates: the caller states what it observed, and we check the world still
matches.

### Keyboard without `window` is refused

Per the intent's fail-closed constraint. This is a breaking change for any caller
that types today, and it is deliberate: the alternative is a default that is
silently unsafe, which is what we are fixing. The refusal names the remedy —
call `windows`, pick the address, pass it.

Pointer actions are unchanged and do not take it.

### Pointer actions stay as they are

Open question 2 in the intent, answered no. `frame` already binds coordinates to
an observation. Adding a focus check to clicks would refuse the ordinary case of
**clicking an unfocused window in order to focus it**, which is how a person uses
a desktop and how the agent reaches a window in the first place.

### The check is a positive assertion, not a difference

Written the obvious way this guard fails open:

```python
if focused != pinned:
    refuse()          # "no difference detected" when focused is unknown
```

Written the other way round it cannot:

```python
if focused == pinned:
    proceed()         # everything else -- refuse
```

`{}` from an empty workspace, `None`, a raised `RuntimeError`, a malformed reply
and a genuinely different address all land in the same branch, so the guard needs
no knowledge of which of those Hyprland produces. **It requires proof to proceed
rather than proof to refuse.**

This is #51's bug in nixarchy-voice, stated as a shape so it cannot recur here:
there `_query_json` returned `[]` on failure, the guard asked "are there
sensitive windows?", read "none found", and proceeded — absence of evidence taken
as evidence of absence. `host.ctl` (`host.py:20`) already raises rather than
returning empty, so ai-mirror does not have that defect today; writing the
comparison positively means a future change to `ctl` cannot introduce it either.

The refusal still distinguishes *why* for the model's benefit — "focus is a
different window" and "focus could not be determined" are different remedies —
but both refuse, and that decision is taken before the message is chosen.

### Cost

`hyprctl activewindow -j` measured at **0.01 s** on this host, against
`hyprctl clients -j` at 16-17 ms (#23): one window rather than all of them. Per
keyboard line that is acceptable, and it is only paid by batches that type.

### The success message stops overstating

A delivered keystroke currently reads as plain success. It becomes explicit that
delivery to a named window is all that has been established — not that the
application accepted it, and not that the task completed. Borrowed wording from
the prior art, which is right about this: *dispatch success is not task
completion*.

## Alternatives rejected

- **Pin the focused window at batch start.** Does not fix the reported incident,
  as above. It would have blessed the wrong window.
- **Reuse `generation` as the pin.** Control is held across many focus changes,
  so a generation-scoped pin authorises typing into a window focused ten actions
  ago — the original bug with a badge on.
- **Check once per `input` call instead of per line.** A batch is not atomic;
  the ownership check is per line for exactly this reason, and focus moves at
  least as easily as ownership does.
- **Allow keyboard without `window` and merely report honestly.** Honest text
  does not stop a keystroke reaching a delete-confirmation dialog.
- **Port `verified_input.py` wholesale.** Its `InputGuard` holds a pin across a
  long-lived conversation object we do not have, and it re-derives focus through
  its own `execute("list_windows")` indirection. The idea ports; the object does
  not.
- **Include the editor-detection and "please…"-text heuristics now.** Deferred to
  their own issue: both are heuristics on *content and process tree* rather than
  on state, they share a shape with the sensitive-window patterns (#19), and a
  wrong refusal from either is invisible to the user. They deserve their own
  evidence rather than riding in on this one. (Intent open questions 3 and 4.)

## Risks

- **Breaking change.** Every caller that types must now pass `window`. Mitigated
  only by the refusal being explicit about the remedy; there is no compatible
  middle that is also safe.
- **A named window can vanish** between `windows` and the keystroke. That is the
  case the check is for, and it produces a refusal rather than a stray keystroke.
- **10 ms per keyboard line** on a long batch. Paid only by keyboard batches, and
  small beside the helper's own round trip.
- **`activewindow` on an empty workspace** returns no address. Handled by the
  positive comparison above rather than by a special case, so it needs no
  behaviour of Hyprland's to be known in advance. A test still covers it, for the
  quality of the message rather than the safety of the decision.

## Verification

- Unit: a keyboard batch whose `window` does not match focus sends **no helper
  line** — asserted on the helper, not on the returned message. A guard that
  refuses after typing would pass a message-level assertion.
- Unit: focus changing **mid-batch** aborts the remainder, mirroring the existing
  ownership-change test.
- Unit: keyboard without `window` is refused; pointer without `window` still
  works.
- Unit: `activewindow` returning nothing refuses rather than passing.
- `nix flake check` green, full suite green.
- Manual: type into a named terminal, then repeat while focus is moved between
  the call and the keystroke, and confirm the second refuses.
