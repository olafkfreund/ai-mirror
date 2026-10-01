---
status: approved
issue: 48
spec: spec/2026-09-28-48-dialog-stray-key.md
---

# Plan: A stray keystroke cannot grant control

Branch `fix/48-dialog-stray-key`, on `master` at `a501317`.

## Approved decisions (self-contained)

- **The rule is in one pure function.** `decide(state, key, modifiers)` lives
  in a new `plugin/ConfirmKeys.js` (`.pragma library`, no imports). It reads
  key codes from the `Qt` global. It returns
  `{answer: "confirm"|"deny"|null, keyArmed: bool}`. The QML only applies
  the result.

  | state | key | result |
  |---|---|---|
  | any | modifier alone: Shift, Control, Alt, AltGr, Meta, Super_L, Super_R, CapsLock | nothing (`answer: null`, `keyArmed` unchanged) |
  | any | Escape, Return, Enter, D | deny |
  | unarmed | Left, Right, Up, Down, Tab, Backtab | `keyArmed: true` |
  | unarmed | anything else, `A` included | deny |
  | armed | `A` with none of Control, Alt or Meta held (Shift is fine) | confirm |
  | armed | arrow, Tab, Backtab | nothing |
  | armed | anything else | deny |

  Rows are checked in table order: modifiers first, then the deny keys.
- **Clicks arm separately.** `pointerArmed` is set once the pointer has moved
  more than 8 logical px from the first position the full-window hover area
  reported. Allow's click grants only if `pointerArmed || keyArmed`;
  otherwise it is ignored. Pointer movement never arms the keyboard. Both
  flags reset when a new request opens.
- **Labels.**
  - Allow reads `Allow (→ then A)` until `keyArmed`, then `Allow (A)`.
  - Deny stays `Deny (Esc)`.
  - While unarmed, a hint line reads "Typing? Your next key denies this."
- **Tests.** `tests/test_confirm_keys.mjs` runs under `node --test`. It loads
  the shipped JS through `node:vm` with a `Qt` stub carrying Qt 6's numeric
  values. `flake.nix` gains `checks.confirm-keys`, with node as a
  check-only input.
- **Unchanged:** `control.py`, the CLI, MCP, the layer, the namespace and
  exclusive focus.

## Steps

1. **`plugin/ConfirmKeys.js` (new).**
   - The first line is `.pragma library`.
   - Define `ARMING`, `MODIFIER_ONLY` and `ALWAYS_DENY` as arrays of
     `Qt.Key_*`, plus `function decide(state, key, modifiers)`, implementing
     the table in its row order.
   - "Ctrl/Alt/Meta held" is
     `modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)`.
   - Build the arrays *inside* `decide`, or in a function it calls. In a
     `.pragma library` file, module-level `Qt` access is fine in QML, but the
     node test installs its stub before evaluation either way.
   - A short header comment states the rule and points to #48.
   - → verify: step 2's test.
   - Traps: no `import`, no QML types; plain ES5-compatible JS (`var`,
     `function`). Keep it under about 40 lines.

2. **`tests/test_confirm_keys.mjs` (new).**
   - Read `plugin/ConfirmKeys.js`, strip the `.pragma library` line, and run
     it with `vm.runInContext` in a context whose `Qt` is a stub with these
     Qt 6 values:
     - Keys: `Key_A` 0x41, `Key_D` 0x44, `Key_Escape` 0x01000000, `Key_Tab`
       0x01000001, `Key_Backtab` 0x01000002, `Key_Return` 0x01000004,
       `Key_Enter` 0x01000005, `Key_Left` 0x01000012, `Key_Up` 0x01000013,
       `Key_Right` 0x01000014, `Key_Down` 0x01000015, `Key_Shift`
       0x01000020, `Key_Control` 0x01000021, `Key_Meta` 0x01000022,
       `Key_Alt` 0x01000023, `Key_CapsLock` 0x01000024, `Key_Super_L`
       0x01000053, `Key_Super_R` 0x01000054, `Key_AltGr` 0x01001103.
     - Modifiers: `ShiftModifier` 0x02000000, `ControlModifier` 0x04000000,
       `AltModifier` 0x08000000, `MetaModifier` 0x10000000.
     - Make the stub a `Proxy` that **throws on any unknown name**, so a typo
       or a missing key cannot silently be `undefined`.
   - Asserts:
     - Every table row.
     - The words "banana", "hello" and "a" (letters as `0x41 + i`) deny on
       their first key.
     - `Right` then `A` → confirm.
     - `Shift`, `Right`, then `A` with Shift → confirm.
     - `Ctrl+A` → deny in both states.
     - `D` and `Escape` deny when armed too.
     - A modifier alone leaves `keyArmed` untouched in both states.
   - Use `node:test` and `node:assert/strict`, with no npm packages.
   - → verify: `node --test tests/test_confirm_keys.mjs` → all pass.
   - Traps:
     - `python3 -m unittest discover` must not pick this file up. The
       `test*.py` pattern already excludes it.
     - Do not add a `package.json`.

3. **`flake.nix:109-110`: add a check** next to `unittest`:
   ```nix
   confirm-keys = pkgs.runCommand "ai-mirror-confirm-keys" { nativeBuildInputs = [ pkgs.nodejs ]; } ''
     cd ${./.}
     node --test tests/test_confirm_keys.mjs
     touch $out
   '';
   ```
   - → verify:
     `nix build .#checks.x86_64-linux.confirm-keys -L`, then
     `nix flake check`.
   - Traps:
     - The source is read-only, so do not write into `${./.}`. node writes
       nothing, but if it does, copy to `src` as `unittest` does.
     - Node goes only in `checks`, not in `packages` or the plugin.

4. **`plugin/AgentConfirmDialog.qml`: wire it.**
   - After the existing imports, add `import "ConfirmKeys.js" as ConfirmKeys`.
   - On `root`, add `property bool keyArmed: false`,
     `property bool pointerArmed: false` and `property var pointerStart: null`.
   - Line 35, `onOpenedChanged`: when opened, reset all three before forcing
     focus.
   - Lines 65-71, `Keys.onPressed`:
     ```qml
     var r = ConfirmKeys.decide({ keyArmed: root.keyArmed }, event.key, event.modifiers)
     root.keyArmed = r.keyArmed
     if (r.answer) root.answer(r.answer)
     event.accepted = true
     ```
     The dialog holds exclusive focus, so every key is the dialog's to
     consume.
   - Add a full-window `MouseArea` as the first child of the `PanelWindow`
     (before `BorderSurface`), so it sits beneath the buttons:
     `anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton`.
     Its `onPositionChanged: function (m)`:
     - if `root.pointerStart` is null, set it to `{x: m.x, y: m.y}`;
     - else, if `Math.hypot(m.x - pointerStart.x, m.y - pointerStart.y) > 8`,
       set `root.pointerArmed = true`.
   - Line 110, Allow's `MouseArea`:
     `onClicked: if (root.pointerArmed || root.keyArmed) root.answer("confirm")`.
   - Labels and hint:
     - Allow's text becomes
       `root.keyArmed ? "  Allow (A)  " : "  Allow (→ then A)  "`.
     - Add a `Text` "Typing? Your next key denies this." after the body
       `Text`, with `visible: !root.keyArmed`, in the same font and colour
       as the body text and `textFormat: Text.PlainText`.
   - Update the header comment (lines 8-14) to state the new rule in two
     sentences.
   - → verify: `nix build .#plugin`. Then
     `grep -c ConfirmKeys result/AgentConfirmDialog.qml` gives at least 2,
     and `ls result/ConfirmKeys.js` exists. `nix flake check` runs the
     plugin check (no symlinks).
   - Traps:
     - Do not touch `answer()`, the layer, the namespace or `keyboardFocus`.
     - The hover `MouseArea` must use `Qt.NoButton`, or it will swallow
       clicks meant for Deny and Allow.
     - The QML cannot be loaded outside the shell, so get it right by
       reading. The live check in step 6 is the real test.

5. **Docs.**
   - `AGENTS.md:36` (code map), replace "Deny on Escape/Enter, Allow on `A`"
     with "an arrow or Tab arms Allow, then `A`; any other first key denies
     (`ConfirmKeys.js`)".
   - Add a code-map row for `plugin/ConfirmKeys.js`.
   - `docs/usage.md:9`, replace "**A** allows, **Escape** (or Enter, or
     Deny) refuses" with "**→** (or Tab) then **A** allows; **Escape**,
     Enter, Deny, or any other first key refuses: typing when it appears
     denies it".
   - → verify: read back.
   - Traps: do not add to `gotchas.md`. The default index is at its
     20000-byte cap (`test_invariants`), and agents do not answer this
     dialog.

6. **Live check (the human answers; the agent only asks).** For each case,
   run `ai-mirror control agent`, let the human act, then read
   `ai-mirror status`:
   1. Type `a` straight away → `off`.
   2. `→`, then `a` → `agent`; then `control off`.
   3. `Esc` → `off`.
   4. Click Allow without moving the mouse → still `pending`. Then move the
      mouse and click Allow → `agent`; then `control off`.
   5. `Ctrl+A` → `off`.
   6. Also confirm that the label reads "→ then A" before arming and "A"
      after, and that the hint line disappears on arming.

   - → verify: outcomes pasted into the PR.
   - **Loading the new dialog.** On this host the plugin is a Home Manager
     symlink, `~/.config/omarchy/plugins/olafkfreund.ai-mirror` →
     `/nix/store/…-ai-mirror-plugin-2.0.0`. Before the test, **ask the
     human** which of these to use:
     - (a) Temporarily repoint that symlink at `nix build .#plugin`'s
       output, reload the shell, test, then restore the original target
       recorded beforehand and reload again.
     - (b) The human rebuilds their configuration from this branch.

     Do not do either without the answer. **Answered at plan approval:
     (a).** The human said "use your recommendations", and (a) is the one
     that is quick and fully reversible.
   - Traps: confirm by seeing the new label that the new dialog is the one
     answering. If the old one answers, the test proves nothing.

## Tests

```sh
python3 -m unittest discover -s tests              # unchanged, 209 OK
node --test tests/test_confirm_keys.mjs           # all pass
nix flake check                                   # includes confirm-keys and plugin
```

## Rollback

Revert the implementation commits. The dialog goes back to "A allows",
nothing persists, and the state file format is unchanged.
