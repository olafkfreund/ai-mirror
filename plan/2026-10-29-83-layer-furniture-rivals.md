---
status: approved
issue: 83
spec: spec/2026-10-29-83-layer-furniture-rivals.md
---

# Plan: typing into a panel works when only the desktop's furniture shares its level

## Approved decisions (from the spec)

- **Furniture** means a layer surface mapped continuously since the grant:
  `baseline_layers` minus anything seen to leave (#39). It is matched by namespace,
  as today. There is one definition, used by both guards.
- **Option (b):** a surface blocks typing into a layer target when
  - it is at a **higher** level than the target, furniture or not; or
  - it is at the **same** level and is not furniture.

  Lower levels never block, as today.
- **No baseline** in state (`baseline_layers` absent, or `None`) keeps today's rule:
  every other surface at the same level or above blocks.
- **A failed `host.layers()`** still falls through to `_require_focus` in
  `_require_target`, so a layer target is refused. That stays unchanged.
- **The refusal message** stays "another surface is open at the same level or above:
  {names}; cannot tell which has the keyboard, so input was NOT sent. …" and names
  only the surfaces that actually block.
- **No namespace allowlist.** No change to `_require_target`, `run_batch` or the
  key-release rescue.

## Steps

1. **`src/ai_mirror/control.py:685-745`, extract `_furniture`.**
   - Move the baseline bookkeeping out of `_refuse_new_surfaces` into a new
     `_furniture(mapped: list[dict]) -> tuple[list[str], list[str]] | None`,
     defined just above `_refuse_new_surfaces`. It covers:
     - `read_state()`;
     - `baseline = state.get('baseline_layers')`, returning `None` if it is `None`;
     - computing `present`, `still` and `departed`;
     - the locked re-read and `_write` of `baseline_layers` / `baseline_departed`
       when something left.

     It returns `(still, departed)`.
   - `_refuse_new_surfaces` keeps its own `host.layers()` call and `except`
     (a failed query returns), calls `_furniture(mapped)`, returns on `None`, and
     builds `new`, `returned` and `appeared` and its message exactly as now.
   - Move the docstring paragraphs that describe the baseline into `_furniture`;
     `_refuse_new_surfaces` keeps the "why refuse" paragraphs.

   Verify: `python -m unittest discover -s tests` passes unchanged (326 tests). This
   step is a pure refactor.
   Traps:
   - The re-read inside `locked('control')` must stay: a grant can end between the
     read and the write (comment at ~721).
   - Keep "every level" in `present`: the wallpaper is at level 0 (comment at ~709).
2. **`src/ai_mirror/control.py:747-777`, `_require_layer` uses furniture.**
   - Inside `_require_layer`, after the focus read, call
     `furniture = _furniture(layers)`, reusing the list `_require_target` already
     fetched. Do not query again.
   - Rivals become: `other['address'] != layer['address']` and
     (`other['level'] > layer['level']`, or
     (`other['level'] == layer['level']` and
     (`furniture is None` or `str(other.get('namespace') or '') not in furniture[0]`))).
   - Add one docstring paragraph: same-level furniture (#39's definition) isn't a
     rival, because it is the shell's own always-mapped surface; furniture above
     still is (#83, option b).
   - Message text unchanged.

   Verify: the suite still passes. The existing
   `test_another_surface_at_the_same_level_refuses_and_names_it` keeps passing,
   because its toast is not in the baseline.
   Traps:
   - `_furniture` writes state when furniture has left. That is the intended shared
     bookkeeping. Calling it from the layer path is fine.
   - Don't catch `_furniture` exceptions into "allow": a state read error must
     propagate as it does from the window path.
3. **`tests/test_layer_typing.py`, new class `TypingBesideFurniture(Base)`**, after
   `TypingIntoASurface` (~line 186).
   - Grant with `FURNITURE + [layer(TOAST, 'omarchy-notifications', 3)]` mapped
     (patch `host.layers` around `grant()`).
   - Reuse the `run_on` helper shape from `TypingIntoASurface` (copy it or
     subclass).
   - Tests:
     - **a)** `OPEN + [toast]` → panel typed into (`helper.sent == ['T hi']`).
     - **b)** `OPEN + [toast] + [layer('0x5efa93100000', 'osd', 3)]` →
       `wrong_target` naming `osd` and not `omarchy-notifications`.
     - **c)** Furniture left and came back: run once with `OPEN` (no toast), which
       records the departure, then `OPEN + [toast]` → `wrong_target` naming
       `omarchy-notifications`.
     - **d)** Furniture above: panel at level 2
       (`FURNITURE + [layer(PANEL, 'launcher', 2), toast]`) → `wrong_target`.
     - **e)** No baseline: grant with `host.layers` raising `RuntimeError`, so no
       baseline is recorded (`_baseline_layers` returns `None`), then
       `OPEN + [toast]` → `wrong_target` (today's rule).

   Verify: run the suite with and without the signature:
   - `python -m unittest discover -s tests`
   - `env -u HYPRLAND_INSTANCE_SIGNATURE python -m unittest discover -s tests`

   Both pass, with 331 tests.
   Traps:
   - The `Base` setUp stubs `_instance_running` and pins `test_sig`. Don't undo it.
   - Check that (e) really grants: if the grant raises because of the layers
     failure, record that and use
     `patch.object(control, '_baseline_layers', return_value=None)` instead.
4. **`src/ai_mirror/gotchas.md:199-203`**: replace "Refused while another surface is
   at the same level or above (a notification over a menu): wait and retry." with:
   "Refused while another surface is above it, or at its level and not part of the
   desktop since the grant (a notification that popped up over a menu): wait and
   retry. Surfaces mapped the whole time since the grant (the shell's notification
   host, accent-hold) are furniture and don't block at the same level (#83)."

   Verify: `grep -n '#83' src/ai_mirror/gotchas.md`.
   Traps: `gotchas.md` is hand-written and human-reviewed (its header). The PR
   names this edit.

## Tests

- `python -m unittest discover -s tests`, with and without
  `HYPRLAND_INSTANCE_SIGNATURE`: all pass (331).
- `nix flake check` (CI `check`): green.
- **Live, after deploy** (nixarchy edge tracks ai-mirror master, then p620's lock and
  `just p620`, then a fresh Claude session so the MCP server is new):
  1. take control and press SUPER+H;
  2. `windows` gives Nixi's layer address;
  3. `input` with `type`, `window=<nixi address>`.

  The text appears in Nixi's box, with no `wrong_target`.

## Rollback

Revert the merge commit on ai-mirror master. The lock moves back on the next
`nix flake update`, or pin `4edc198`/`b4a9ae6` in nixarchy temporarily. No state
format changes: `_furniture` reads and writes the same `baseline_layers` and
`baseline_departed` keys.
