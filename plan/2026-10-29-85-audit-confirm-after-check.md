---
status: draft
issue: 85
spec: spec/2026-10-29-85-audit-confirm-after-check.md
---

# Plan: the audit never records a grant that did not happen

## Approved decisions, carried over

- In `_answer`, the grant-only preconditions (`_baseline_layers()`, then the
  instance read and `_instance_running` check) move above `audit(...)`.
  They run only when `granted`, in their current order.
- A refused confirm writes **no** audit line (intent decision 1). It still
  raises `bad_request`, and the request stays `pending`.
- Denial, the audit line's fields, the gate's decisions, and the MCP and CLI
  surface are all unchanged.
- The audit is not moved after `_write`: a grant with no record is worse.

There are two steps and two files, below the coder hand-off threshold, so
Opus implements them. A fresh Opus agent reviews.

## Steps

1. **`tests/test_instance_resolve.py:220-224`**
   (`test_a_grant_is_refused_when_its_hyprland_is_not_running`): after the
   existing assertions, assert that no audit entry has `event == 'confirmed'`.
   Read the entries with `control.read_audit(0)['entries']`, as
   `test_audit_answerer.py` does.
   - Verify: `python3 -m unittest tests.test_instance_resolve -k refused`
     **fails** on the unfixed code. Paste the red output in the PR.
   - Traps:
     - The `Grants` base stubs `_is_hyprland` and `host.layers`. Keep this
       test inside that class.
     - Tests cannot reach the desktop (`guard.arm()`).

2. **`src/ai_mirror/control.py:456-473`** (`_answer`): insert
   `if granted:` with the moved `baseline = …`, `instance = …` and the
   check-and-raise, between `generation = …` and `audit(...)`. Delete
   those lines from their old place. Keep the two comments ("after the
   baseline: …", "an unstamped grant …").
   - Verify:
     - the step 1 test passes;
     - `python3 -m unittest discover -s tests -v` is all green;
     - `node --test tests/test_confirm_keys.mjs` passes;
     - `nix flake check` passes.
   - Traps:
     - `granted_state` still sets `instance` and `baseline_layers` from the
       moved variables, which exist only on the granted path. The deny path
       returns before using them.
     - No new dependencies, and no change to the audit's line format.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_confirm_keys.mjs
nix flake check
```

Expected: all green. Step 1 is seen red before step 2.

## Rollback

Revert the commit. There is no state or format migration.
