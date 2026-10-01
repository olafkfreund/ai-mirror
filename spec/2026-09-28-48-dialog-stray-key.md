---
status: draft
issue: 48
intent: intent/2026-09-28-48-dialog-stray-key.md
---

# Spec: A stray keystroke cannot grant control

## Design

### 1. The rule lives in one pure function

There is a new `plugin/ConfirmKeys.js`, a QML `.pragma library` module with
no imports. It exports one function:

```js
// state: {keyArmed: bool}. Returns {answer: "confirm"|"deny"|null, keyArmed: bool}.
function decide(state, key, modifiers)
```

`AgentConfirmDialog.qml` imports it (`import "ConfirmKeys.js" as ConfirmKeys`),
calls it from `Keys.onPressed` (`AgentConfirmDialog.qml:65-71`), and applies
the result. The QML keeps no rule of its own. This is the part that can be
tested without a desktop or the Omarchy shell, whose `qs.*` imports make the
dialog itself unloadable in a test.

The rule (intent Q1, option (d), "the first key decides"):

| state | key | result |
|---|---|---|
| any | a modifier alone (Shift, Ctrl, Alt, AltGr, Meta, Super L/R, CapsLock) | nothing |
| any | Escape, Return, Enter, `D` | deny |
| unarmed | an arrow, Tab, Backtab | arm Allow |
| unarmed | anything else, `A` included | **deny** |
| armed | `A` with no Ctrl, Alt or Meta held (Shift allowed) | confirm |
| armed | an arrow, Tab, Backtab | nothing |
| armed | anything else | deny |

Modifiers on their own are ignored in both states. Otherwise pressing Shift
to type a capital `A` would deny a request the human meant to allow. A
modifier is never a decision; the key after it is. `Ctrl+A` (select all, a
common keystroke mid-typing) denies when unarmed and does not grant when
armed.

`keyArmed` resets to false whenever a new request opens
(`onOpenedChanged`, line 35), so arming never carries over to the next
request.

### 2. Clicks are armed by moving the pointer, separately from keys (intent Q2)

A second flag, `pointerArmed`, lives in the QML. A full-window `MouseArea`
with `hoverEnabled: true` and `acceptedButtons: Qt.NoButton` records the
first pointer position it sees, and sets `pointerArmed` once the pointer is
more than 8 logical pixels from it. The surface appearing under a resting
pointer reports a position without any movement, so that first report must
not arm.

The Allow `MouseArea` (line 110) grants only if `pointerArmed || keyArmed`.
Otherwise the click is ignored. Deny's `MouseArea` (line 103) is unchanged.

**The flags stay separate on purpose.** If moving the pointer armed the
keyboard, a human typing while nudging the mouse would grant on their next
`a`. Moving the pointer arms only clicks. An arrow key arms both: it is a
deliberate act. Both flags reset when a new request opens.

### 3. The dialog says what to do (intent Q3)

- The Allow label reads `Allow (→ then A)` until `keyArmed`, then
  `Allow (A)`.
- The Deny label reads `Deny (Esc)` as now.
- One line is added under the body text: "Typing? Your next key denies
  this." It is shown while unarmed.

No colour or layout changes.

### 4. Tests

The repo has no JavaScript test runner. `tests/test_confirm_keys.mjs`
reads `plugin/ConfirmKeys.js`, drops the `.pragma library` line, evaluates
the rest with `node:vm`, and asserts:
- every row of the table;
- that a typed word ("banana", "hello", "a") denies on its first key;
- that `Right` then `a` grants;
- that `Shift`, then `Right`, then `Shift+A` grants;
- that `Ctrl+A` never grants.

`flake.nix` gains `checks.confirm-keys`, a `runCommand` with
`nativeBuildInputs = [ pkgs.nodejs ]` that runs `node --test`. Node is a
check-time input only. Nothing that ships gains a dependency, and the
plugin directory gains one `.js` file and no symlinks.

### 5. What does not change

- `control.py`: `confirm_request` and `deny_request`, the 30 s expiry, and
  the state file.
- The CLI and MCP.
- The dialog's layer, namespace and exclusive keyboard focus.

## Alternatives rejected

- **(a) Arrow-arming alone (omarchy-omcp).** Arrow-then-letter is ordinary
  editing.
- **(b) A time window.** It guesses at reaction time. It also leaves the
  dialog open for the next key instead of resolving it.
- **(c) Both.** It inherits (b)'s guess.
- **A random code to type.** Strong, but it adds friction to every grant,
  and (d) already reaches a similar accident rate by failing closed.
- **Testing the QML with `qmltestrunner`.** The dialog imports `qs.*`
  modules that exist only inside the Omarchy shell, so it cannot load
  standalone. Testing the extracted JS covers the rule. The wiring is
  covered by the live check.
- **Duplicating the rule in Python to test it there.** Two copies drift.
  The test must run the code that ships.

## Risks

- **More denials.** A human who reaches for the keyboard to approve and
  presses `A` first gets a deny. The agent sees `owner: off`, and the gotcha
  says not to ask again unprompted. The label "→ then A" exists to prevent
  this. It is the safe failure, and the intent chose it.
- **Key names on Quickshell's Qt 6.** `Qt.Key_Backtab`, `Key_AltGr` and
  `Key_Super_L/R` must exist there. Unknown names would be `undefined`, and a
  table lookup would silently miss them. The JS reads `Qt.Key_*` and
  `Qt.*Modifier` from the `Qt` global, which `.pragma library` scripts have.
  The node test provides a `Qt` object with Qt 6's documented numeric
  values, and asserts that none of the names the module uses is
  `undefined`. The live check confirms the real ones.
- **Hover never firing.** If the layer surface delivers no hover events,
  `pointerArmed` never sets, and Allow-by-click only works after an arrow
  key. That fails closed, and the live check reveals it.
- **Kill switch:** unaffected. Super+Shift+Escape is a compositor bind, and
  a modifier press reaching the dialog is ignored.

## Verification

- `nix flake check` runs `confirm-keys` and the existing checks, all green.
  `python3 -m unittest` is unchanged.
- **Live, by the human:** the human answers, and the agent only asks. Five
  requests from `ai-mirror control agent`:
  1. Type `a` straight away → denied.
  2. Press `→` and then `a` → granted; then `control off`.
  3. Press `Esc` → denied.
  4. Click Allow without moving the mouse → nothing happens; then move the
     mouse and click → granted; then `control off`.
  5. Type `Ctrl+A` → denied.

  Record each outcome from `status`/`audit` in the PR.
