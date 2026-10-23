---
status: draft
issue: 70
spec: spec/2026-10-23-70-a11y-value-selection.md
---

# Plan: set values and select items without the pointer

Self-contained. Branch `feat/70-a11y-value-selection`, stacked on
`fix/65-background-a11y-act` (PR #67). Line numbers as of `eef21dc`; re-find
by the quoted text if they drift.

## Approved decisions (from the spec)

1. **Measure first** (GTK4, Firefox, Chrome with a scratch profile and
   `--force-renderer-accessibility`): which controls implement `Value` /
   `Selection`, at which depth, and whether using them moves the pointer,
   focus, the active window, or maps a surface. Rows go into the **existing**
   measured table in `gotchas.md` (index cap 22,000 bytes, <1 KB left).
   Decides `SELECTION_DEPTH` (default 2) and closed-`<select>` reachability.
2. **Rows** gain `value: [current, minimum, maximum, step]` when
   `get_value_iface()` is present and `current` is finite; an unreadable or
   non-finite bound/step is `None`, never `nan`. `_states()` does not read
   values. `_actionable` counts `value`; the quiet-role filter keeps it.
3. **`set_value`**: `value` an `int`/`float`, finite, not `bool`, validated
   before `resolve` (with `timeout`). No `Value` → `unsupported`. Range check
   only when both bounds are finite and `minimum < maximum` → `invalid`
   before writing. `eps = 1e-5 * max(1.0, abs(value))`;
   `tol = max(step / 2, eps)` when `step` is finite and `> 0`, else `eps`.
   Already set (within `eps`) → no write. Write through `_write`; falsy →
   `unavailable`. Read-back: finite and within `tol` → verified; else
   `not_confirmed`, `details={'value': current, 'wanted': value}`.
4. **`select`** on the item's own id. For `k` in
   `1..min(SELECTION_DEPTH, len(parts) - 1)`: container
   `'.'.join(parts[:-k])`, `index = int(parts[-k])`, selected node
   `'.'.join(parts[:len(parts) - k + 1])`. First container with
   `get_selection_iface()` wins; none → `unsupported`. `expect` is the guard
   (role, name of the item). Already selected → no write. Write through
   `_write`; falsy → `unavailable`. Read-back: re-resolve selected node and
   container each probe, `stale_node` from either → not yet; confirmed only
   when the selected node has its original role **and** (`selected` in its
   states **or** `is_child_selected(index)`). States and `selected: {role,
   name}` describe the selected node; `selected_via: k`.
5. **One result shape** for both: `ok, node, action, verified, changed,
   states_before, states_after, waited_ms` + `value_before, value_after`
   (`set_value`) or `selected, selected_via` (`select`). Already-there path:
   `changed: false`, `waited_ms: 0`.
6. A read-back failure after a delivered write says so (`details.delivered`),
   as #65's `_read_back` does. No deselect, no clear.

## Steps

1. **Measure (session model, live; no code).** Ask for control through the
   confirm dialog. On a scratch workspace shown on a monitor the human is not
   using (Firefox exposes no content on a hidden workspace, measured in #65;
   GTK4 and Chrome also work hidden), with the human's window focused, launch
   the apps; for Firefox and Chrome open a scratch page with
   `<input type="range" min=0 max=10 step=1>`, `<input type="number">`, a
   closed `<select>`, `<select size=4>`, a `role=tablist`, and a list box.
   Read the tree (`ai-mirror a11y-tree --app <name>`) and, with a short
   `nix develop -c python3` probe, record per control: `get_value_iface()` /
   `get_selection_iface()` on the node and up to 3 ancestors, values, bounds,
   step. Then, for each write, the probe goes through ai-mirror's own gate,
   never around it: `control.require_agent(gen)` (owner + generation, so a
   revocation stops it), `acc, At = a11y.resolve(node_id)` (privacy check),
   and `a11y._write('measure', lambda: iface.set_current_value(v))` /
   `... sel.select_child(i)` (the guarded seam); record before/after
   `hyprctl cursorpos`, `activewindow`, focused node and new layers. `control off` after. → verify by: a row per app ×
   control in the PR description, and `SELECTION_DEPTH` decided.
   Traps: silence notifications first and restore them; close every test
   window; a GTK4 `set_text`-style read that returns nothing is a finding,
   not a failure.

2. **`src/ai_mirror/a11y.py`: reading values.** Add `import math`. Add
   ```python
   def _finite(x):
       return type(x) in (int, float) and math.isfinite(x)
   ```
   `_node(acc, node_id, Atspi, value=True)`: after the text block (~line 146),
   when `value` and `(v := _call(acc.get_value_iface)) is not None`, read
   `current`, `minimum`, `maximum`, `step` with `_call` from exactly
   `v.get_current_value`, `v.get_minimum_value`, `v.get_maximum_value`,
   `v.get_minimum_increment` (a guessed name such as `get_step` passes every
   `MagicMock` test and silently yields `None` live -- so the tests use a
   `MagicMock(spec=[...])` limited to those four plus `set_current_value`)
   (never the names
   `min`/`max`: `_node` already calls the built-in `min(count, 120)`), and when
   `current` is finite set `row['value'] = [current, minimum if
   _finite(minimum) else None, maximum if _finite(maximum) else None, step if
   _finite(step) else None]`. `_states` (line 373) calls
   `_node(acc, node_id, Atspi, value=False)`. `_actionable` (line 212) adds
   `or row.get('value')`. The quiet-role filter (line 256) adds
   `and 'value' not in row`.
   Tests (`tests/test_reporting_truth.py`, a new class `ValueRows`, fake
   accessibles via `MagicMock`): value present only when the iface is; `nan`
   bound becomes `None`; `nan` current omits the field; `_states` never calls
   the value iface; `_actionable` true for a value-only row at content depth;
   `tree()` keeps a quiet-role row with a value (stub `_walk`).
   → verify by `python3 -m unittest discover -s tests`.
   Traps: reads stay unguarded; never emit `nan` (JSON).

3. **`a11y.py`: `set_value`.** `act(..., timeout=None, value=None)`. Right
   after the `timeout` validation: if `action == 'set_value'` and not
   `_finite(value)` → `ValueError('set_value needs a finite number value')`
   (bools excluded by `_finite`'s `type(...) in` test). The branch goes as the
   **first `if` inside `act()`'s existing `try:`** (line ~390), so every
   AT-SPI call before the write -- `get_value_iface()`, the bound reads -- is
   covered by `act`'s `except (MirrorError, guard.Blocked): raise` /
   `except Exception: unavailable`: `if action == 'set_value': return
   _set_value(...)`, a new function holding decision 3 end to end: the
   `unsupported` / `invalid` / already-set checks, `_write('set_current_value',
   lambda: iface.set_current_value(float(value)))`, then a `wait.poll` probe
   that only reads -- `resolve` (catching `MirrorError` with code `stale_node`
   as "not yet", exactly as `_read_back` does; any other code re-raises), role
   compare, `get_current_value` -- then the result of
   decision 5. Any value placed in a result or in `details` (`value_before`,
   `value_after`, `details.value`) is `None` when not finite -- `nan`/`inf`
   never reach JSON. A poll result of `unavailable` after the write raises
   `unavailable` with `details={'delivered': True}` and "do not repeat it",
   as `_read_back` does.
   Tests (new class `SetValue`, `resolve` and `_write` patched, `timeout=0.1`):
   bool / `nan` / `'3'` → `ValueError` and `_write` not called; out of
   `[0, 10]` → `invalid`, no write; bounds `0..0` or `None` → written; already
   `4` asked `4` → no write, `changed: False`; `4.4` at `4`, step 1 →
   written; read-back `5` for wanted `5` → verified; read-back `4` for wanted
   `5`, step 1 → `not_confirmed` with details; `0.6999999880` for `0.7`, step
   0 → verified; the node `stale_node` on the first probe then back with `5`
   → verified (not `unavailable`); read-back `nan` → `not_confirmed` with `details.value is
   None`; `resolve` raising `sensitive` after the write → `unavailable` with
   `details.delivered`; `_write` falsy → `unavailable`; with the guard armed
   and `_write` unpatched → `guard.Blocked`.
   → verify by the unittest command.
   Traps: `_write` is never called from the probe (`wait.poll` swallows
   every exception, including `Blocked`).

4. **`a11y.py`: `select`.** Module constant `SELECTION_DEPTH = 2` (or the
   step 1 value) with a comment citing #70. In `act`, inside the same `try:`, right after `set_value`'s
   branch: `if action == 'select': return _select(...)`, holding decision 4
   end to end, same `try` shape around `_write('select_child', lambda:
   sel.select_child(index))`, and a reads-only probe. `act` captured the
   *item's* role and `states_before`; when `k > 1`, `_select` resolves the
   selected node (`'.'.join(parts[:len(parts) - k + 1])`) **before** checking
   or writing and takes its role, name and states as the snapshot that the
   already-selected check, the read-back role comparison, `states_before` and
   `selected` use. Delivered-then-unreadable is reported as in step 3.
   Tests (new class `Select`, `resolve` patched by id → fake accessible):
   direct parent (`selected_via: 1`); grandparent (`selected_via: 2`, states
   from the row); none within depth → `unsupported`; id `"3.0"` → stops at the
   application, no `IndexError`; `expect` name mismatch after the list
   shifted (keep the original observation, give the path a sibling with a
   different name) → `stale_node`, `_write` not called; already selected → no
   write; confirmed via `is_child_selected`; confirmed via `selected` state;
   container `stale_node` on the first probe then present → confirmed (not
   `unavailable`); selected node gone → `not_confirmed`; `select_child` falsy
   → `unavailable`; `resolve` raising `sensitive` after the write →
   `unavailable` with `details.delivered`; guard armed → `guard.Blocked`.
   → verify by the unittest command.

5. **Wiring and words.** `api.py:276`: pass `value=args.get('value')`.
   `mcp.py:78`: add `'value': {'type': 'number'}` to `a11y_act`'s properties;
   description adds "set_value (value) on a slider or spin button; select on
   a list or tab item; both read back". `cli.py:111` block: `--value
   type=float`. `docs/usage.md:58` and `:102`: the two actions, `value` in
   rows, `changed`, `value_before/after`, `selected`, `selected_via`.
   `gotchas.md`: step 1's rows into the existing measured table. Tests: MCP
   `validate('a11y_act', {..., 'value': 3.5})` passes, `'value': 'x'` fails;
   CLI parses `--value 3.5`; the index payload stays under 22,000 bytes
   (existing test).
   → verify by the unittest command and `nix flake check`.

6. **Live (session model).** Under a grant from the confirm dialog: one
   `set_value` and one `select` per measured app that supports them; results
   match the table (`verified`, `changed`, states). `control off` after.

## Execution

Steps 2-5 edit four source files and tests across four steps: one `coder`
agent per step in a dynamic workflow in its own git worktree, each step
checked by `codex review --uncommitted` (no custom prompt) and agy
(read-only, one command per call), then committed naming the step; a fresh
Opus review compares `git diff fix/65-background-a11y-act...HEAD` with this
plan. Steps 1 and 6 are the session model's, under the human's grant.

## Tests

```sh
python3 -m unittest discover -s tests -v
nix flake check
```

## Rollback

Revert the step commits. No state, config or plugin changes; existing
`a11y_act` actions are untouched.
