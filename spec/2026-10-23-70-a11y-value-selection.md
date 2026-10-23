---
status: approved
issue: 70
intent: intent/2026-10-23-70-a11y-value-selection.md
---

# Spec: set values and select items without the pointer

## Design

Builds on #65's `a11y_act` (PR #67): the guarded `_write` seam, `_read_back`,
`resolve()`'s privacy check, required `generation`. Two new actions,
`set_value` and `select`, and one new field in tree/find rows.

### 1. Measure first (no code)

As #65's plan step 1: under a grant from the confirm dialog, on a scratch
workspace, launch one window each of the installed apps (GTK4
gnome-calculator / gnome-text-editor, Firefox, Chrome with
`--force-renderer-accessibility` and a scratch profile) on a local page with
`<input type="range">`, `<input type="number">`, `<select>` (closed and
`size=4`), a tab list and a list box. For each control record: whether it
implements `Value` / `Selection` (and on which node -- the item's parent, a
grandparent, ...), its value and bounds, and, with another window focused,
whether `set_current_value` / `select_child` changed the pointer, the active
window, keyboard focus, or mapped a new surface. The table decides
`SELECTION_DEPTH` (below) and whether closed `<select>` items are reachable.
Its rows go into the **existing** measured table in `gotchas.md` (the index
payload has under 1 KB left below its 22,000-byte cap).

### 2. Reading a value (`a11y.py` `_node`, `_actionable`)

`_node(acc, node_id, Atspi, value=True)` gains, when
`acc.get_value_iface()` is not `None`:

```python
row['value'] = [current, minimum, maximum, step]   # floats; step 0.0 if none
```

each read with `_call`. A reading that is `None` or not finite (`nan`, `inf`)
is unreadable: the field is omitted when `current` is; an unreadable bound or
step becomes `None` in the list (never `nan`, which is not valid JSON).
`_states()` calls `_node(..., value=False)`, so `_read_back`'s per-probe cost
does not grow. `_actionable` counts a row with `value` as actionable, so an
unnamed slider is content, and `tree()`'s quiet-role filter
(`a11y.py:256`, `... and 'text' not in row`) also keeps a row that has
`value`, so a counted row is never dropped from `nodes`.

### 3. `set_value` (`a11y.py` `act`)

`act(node_id, action, text=None, expect=None, timeout=None, value=None)`.

- `value` must be an `int` or `float`, finite, not a `bool`; otherwise
  `ValueError`, before anything else (same place `timeout` is validated).
- `iface = acc.get_value_iface()`; `None` →
  `unsupported: this element has no AT-SPI Value`.
- Bounds read through `_call`. If both are finite, `minimum < maximum`, and `value` is outside
  them → `MirrorError('invalid', f'value must be within [{minimum}, {maximum}]')`,
  before any write. Missing or degenerate bounds (`minimum >= maximum`) mean no
  range check.
- **Two tolerances.** `eps = 1e-5 * max(1.0, abs(value))` covers float32
  round-trips (Chromium stores range values as 32-bit floats: 0.7 reads back
  as 0.6999999880...). `tol = max(step / 2, eps)` when `step` is finite and
  `> 0`, else `eps`: half a step accepts a toolkit snapping to the nearest
  representable value but never the adjacent one (5 wanted with step 1 while
  it stays at 4 is not confirmed). Neither reads the bounds.
- **Already set** uses `eps`, not `tol`: only when the current value is the
  requested one is nothing written (`4.4` wanted on a step-1 slider at `4` is
  still written, and then read back against `tol`).
- `_write('set_current_value', lambda: iface.set_current_value(float(value)))`;
  falsy → `unavailable: the application refused the value`.
- Read-back (`_read_back`, new branch): probe re-resolves, compares role, reads
  `get_current_value()`; confirmed when it is finite and
  `abs(current - value) <= tol`. Not
  confirmed (or the value unreadable) → `not_confirmed` with
  `details={'value': current, 'wanted': value}`.
  The result carries `value_before` and `value_after`.

### 4. `select` (`a11y.py` `act`)

The caller names the **item's** node id. Node ids are child-index paths
(`"3.0.2.5"`), so the container and the item's index come from the id itself:

- For `k` in `1..min(SELECTION_DEPTH, len(parts) - 1)` (`SELECTION_DEPTH` a
  module constant, `2` unless the measurement says otherwise; an application
  node is never a container): `container_id = '.'.join(parts[:-k])`,
  `index = int(parts[-k])`, and the **selected node** is
  `'.'.join(parts[:len(parts) - k + 1])` -- the item itself when `k == 1`;
  `container, _ = resolve(container_id)` (privacy re-checked); the first
  container whose `get_selection_iface()` is not `None` is used.
  None found → `unsupported: no ancestor within SELECTION_DEPTH implements
  AT-SPI Selection`.
- If `k > 1`, the selected node is the item's ancestor at that level (a row
  holding cells, say); the result says `selected_via: k`, and
  `states_before` / `states_after` / `selected` describe the selected node,
  since that is where `selected` appears.
- **What guards the target is `expect`, as for every other action.** The item
  resolves and must match `expect` (role, name) when given. A node id is a
  child-index path, and AT-SPI gives no identity beyond what a node reports,
  so if a sibling has slid into the item's slot and shares its role and name,
  nothing can tell them apart -- the description says so, and the result
  names what was selected: `selected: {role, name}` of the item, and for
  `k > 1` of the ancestor actually selected. No second lookup through the
  container: it follows the same current index and proves nothing more.
- Already selected (`'selected'` in the item's states, or
  `sel.is_child_selected(index)`) → nothing written, `verified: true,
  changed: false`.
- `_write('select_child', lambda: sel.select_child(index))`; falsy →
  `unavailable: the application refused the selection`.
- Read-back: each probe re-resolves the selected node and the container,
  treating `stale_node` from either as "not yet" (`False`), never as an error.
  It confirms only when the selected node resolves with its original role
  **and** either it has the `selected` state or the container's
  `is_child_selected(index)` is true -- a gone or changed node never confirms. `states_before` / `states_after` show the
  change; in a single-select container that is how a replaced choice shows.
- Select only: no deselect, no clear (intent question 2).

### 4a. One result shape

Every successful `set_value` / `select` result has the same keys, whether it
wrote or found the state already there: `ok, node, action, verified, changed,
states_before, states_after, waited_ms`, plus `value_before, value_after` for
`set_value` and `selected, selected_via` for `select`. The "already there"
path has `changed: false` and `waited_ms: 0`; a write has `changed: true`.

### 5. Wiring

- `api.py:276`: pass `args.get('value')` to `a11y.act`.
- `mcp.py:78`: schema gains `'value': {'type': 'number'}`; description adds
  "set_value (value) on a slider or spin button; select on a list or tab
  item -- both read back".
- `cli.py:111`: `--value type=float`.
- `docs/usage.md`: the two actions, `value` in rows, the new result fields.

## Alternatives rejected

- **Select by container id + index.** Every other id in the tool names the
  element acted on; an index the caller computes is one more thing to get
  wrong, and the item's own id already encodes it.
- **Use the item's `click` action instead of `Selection`.** Already possible
  today; it is what moves focus (measured in Chrome). `Selection` is the
  interface that says "choose this" without activating anything.
- **Exact-equality read-back for values.** Sliders snap to their step; it
  would report `not_confirmed` for a value that landed.
- **Clamp out-of-range values ourselves.** The caller asked for a value; quietly
  setting another is the false-`ok` shape #65 removed.

## Risks

- **`select_child` on some toolkits may also move focus or activate the item.**
  The measurement records it; the description says only what is measured.
- **An id whose path shifted** between read and act can select a sibling.
  `expect` (role, name) refuses it unless the sibling matches both; when it
  does, the wrong item is selected, and `selected` in the result shows which.
  Same limit every `a11y_act` action has today.
- **Selecting a row via an ancestor (`k > 1`)** selects more than the cell the
  caller named; the result says so with `selected_via`.

## Verification

- Unit tests (fake accessibles, `resolve` and `_write` stubbed, guard armed):
  `value` in rows only for `Value` nodes; `_actionable` true for a value-only
  row; `_states` does not read values; `set_value` validation (bool, nan, str
  → `ValueError` before any write); out of sane range → `invalid`, no write;
  degenerate or unreadable bounds → written and read back without error;
  already at value → no write; refusal → `unavailable`; read-back within half
  a step → verified; the adjacent value (5 wanted, 4 read, step 1) →
  `not_confirmed` with details, and not treated as "already set"; `4.4` on a
  step-1 slider at `4` is written; a float32 round-trip (`0.7` read as
  `0.6999999880...`, step 0) is verified; `nan` and `None` readings never
  reach a comparison or the JSON; `select` direct parent, grandparent
  (`selected_via: 2`), none within depth → `unsupported`; a shallow id
  (`"3.0"` with depth 2) stops at the application, no `IndexError`; the
  container going stale during read-back → polls again, not `unavailable`;
  the selected node gone → `not_confirmed`; `selected_via: 2` reports the
  row's states, not the cell's; the quiet-role filter keeps a value-only row;
  a shifted index -- the original observation
  kept, the child list then shifted so the item's path holds a sibling with a
  different name -- refused by `expect` before any write; already selected →
  no write; read-back confirmed via `is_child_selected`; a guarded
  write in each new branch raises `guard.Blocked`.
- `nix flake check` green.
- Live, under a grant from the confirm dialog: one `set_value` and one
  `select` in the measured apps, results matching the table.
