---
status: draft
issue: 85
intent: intent/2026-10-29-85-audit-confirm-after-check.md
---

# Spec: the audit never records a grant that did not happen

## What can fail after the audit line today

In `_answer` (`src/ai_mirror/control.py:449-481`), everything after
`audit(...)` at `:457`:

| Call | Can it raise? |
|---|---|
| `_a11y_restore` (deny) | No. It swallows `MirrorError` (`:216-224`) |
| `_baseline_layers` | No. It returns `None` on every query error (`:406-425`) |
| instance check, `:470-473` | **Yes:** `MirrorError('bad_request', …)`. This is the bug |
| `_a11y_enable` | No. It swallows `MirrorError` (`:202-213`) |
| `_write` | Only on an I/O error writing `state.json` |

So the instance check is the one ordinary failure, and moving it fixes the
bug.

## Design

In `_answer`, move the two grant-only preconditions above the `audit`
call, in their current order:

1. `baseline = _baseline_layers()`
2. the instance read and check

They run only when `granted`:

```python
generation = int(state.get('generation', 0)) + 1
if granted:
    baseline = _baseline_layers()
    instance = os.environ.get(host.SIG)  # after the baseline: its hyprctl made this live
    if not instance or not _instance_running(instance):
        # an unstamped grant would outlive any restart
        raise MirrorError('bad_request', 'cannot tell which Hyprland this grant is for; is it running?')
audit('confirmed' if granted else 'denied', ...)   # unchanged
if not granted:
    ...                                             # unchanged
granted_state = {...}                               # unchanged
granted_state['instance'] = instance
...
```

- The order baseline → instance is kept. The comment explains why: the
  baseline's `hyprctl` call is what makes the instance in the environment
  live.
- The same answers grant, deny or fail as before. Only the audit line
  moves.
- A refused confirm writes no line (intent decision 1). The request stays
  `pending`, and lapses to `expired` as today.
- Denial is unchanged. Its audit line is still written before
  `_a11y_restore` and `_write`.

## Alternatives rejected

- **Audit after `_write`.** It would also cover an I/O failure. But if the
  audit write then failed, a grant would exist with no record of it. That
  is worse for a trust record than the reverse, and a full `$XDG_RUNTIME_DIR`
  is not this bug.
- **A `confirm_failed` event.** Rejected by intent decision 1.
- **Duplicating the `audit(...)` call into each branch.** It makes the diff
  bigger and gives two copies of eleven fields to keep in step.

## Risks

- **The baseline is now taken before the audit write.** That is a
  `hyprctl layers` query. The audit write is a local file append, so nothing
  between the two can change the snapshot.
- **Tests that count audit lines.** `test_audit_answerer.py` asserts the
  last line after successful confirms. Those still write it. None asserts a
  `confirmed` line for a refused grant (checked: only
  `test_a_grant_is_refused_when_its_hyprland_is_not_running` refuses one,
  and it checks the state only).

## Verification

- `tests/test_instance_resolve.py`,
  `test_a_grant_is_refused_when_its_hyprland_is_not_running`: also assert
  that the audit holds no `confirmed` event. Seen failing before the fix,
  passing after.
- `python3 -m unittest discover -s tests` passes.
- `nix flake check` passes.
