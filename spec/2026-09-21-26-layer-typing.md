---
status: approved
issue: 26
intent: intent/2026-09-21-26-layer-typing.md
---

# Spec: typing into a shell surface, and typing from the CLI

## What was measured

On razer (Hyprland 0.56.0), with nixarchy-pkg's panel (a Quickshell layer
surface, `keyboardFocus: Exclusive`) open, and before it opened:

- `hyprctl -j activewindow` → `{}` while the panel had the keyboard.
- `hyprctl -j layers` → `{monitor: {levels: {"0".."3": [layer…]}}}`. Each
  layer has `address`, `namespace`, `pid`, geometry and `alpha`, and
  **nothing about keyboard interactivity or focus**. Hyprland 0.56 can't
  say which layer holds the keyboard.
- Before: background (0) `omarchy-background`, top (2) `omarchy-bar`. Open:
  plus overlay (3) `nixarchy-pkg-menu 0x5efa92d0b780`, alone at its level.

## Design

### One `window` parameter, whichever kind it names

Intent Q3. `window` keeps its name and meaning, "the thing this
keystroke is for", and may now be a layer's address as well as a
client's. Window and layer addresses are both compositor object
addresses and don't collide. A caller doesn't need a second parameter,
and #24's path for windows is untouched: an address that is a mapped
client goes through `_require_focus` exactly as today.

### A layer target is its exact address, observed first

Intent Q1: the address, not the namespace. It is exact, it's what
`layers -j` gives, and it dies with the surface: a menu closed and
reopened is a new address, so a stale target refuses rather than typing
into its successor. `host.windows()` gains a sibling `host.layers()`
(address, namespace, monitor, level, pid), and the `windows` op returns
`{"windows": [...], "layers": [...]}`, so the agent observes the target
the same way it observes a window.

### The layer guard, per line, positive by construction

Intent Q2. Hyprland can't say which layer has the keyboard, so the guard
asserts the one configuration in which the answer isn't in doubt, and
refuses every other:

1. the named address is a **mapped layer** now; and
2. **no window has focus** (`focused_address()` is `None`), so no
   keystroke can land in an application window, which is #24's guarantee;
   and
3. **no other layer is mapped at the same level or higher**, on any
   monitor. A surface that takes the keyboard does so from the top; with
   nothing beside or above it, the named one is the only candidate.

All three are checked before every line, as #24 checks focus. A failed
query raises `unavailable`; a false condition raises `stale_generation`
with the reason, chosen after the refusal, never as part of deciding it
(#24's rule). Measured on razer, the panel satisfies all three (alone at
overlay, `activewindow` empty).

What it refuses that it arguably needn't: a notification popup at
overlay while a menu is open. That's retryable and says why, and is
better than guessing.

What it still can't rule out: a layer at a *lower* level holding the
keyboard while the named one, above it, doesn't. With (3), that would
need the named surface to be non-interactive while something beneath it
grabs the keyboard exclusively. The note in the result says keystrokes
were delivered, not accepted, as #24's does for windows.

### The CLI names its target

`ai-mirror input` gains `--window ADDRESS`, passed through as `window`.
It is the same parameter, so the CLI and MCP can't diverge, and the CLI
can type again.

### `index` says so

`index`'s gotchas gain one line: to type into a menu, panel or launcher,
open it, call `windows`, and pass the layer's address as `window`.

## Alternatives rejected

- **A separate `surface` parameter.** Two parameters, one meaning. The
  address already says which kind it is.
- **Target by namespace.** Readable but not exact: a reopened menu has the
  same namespace and would be typed into without having been observed.
- **Trust `activewindow == {}` alone.** Holds on an empty workspace too,
  and says nothing about *which* layer has the keyboard. It's condition 2,
  not the guard.
- **Hyprland's event socket.** No layer-focus event exists in 0.56 to
  listen for.

## Risks

- **Refusals when an overlay is busy** (notification toasts, OSD):
  retryable, and the message names the other layer.
- **`windows` output grows a key.** An additive change to a JSON object;
  callers that read only `windows` are unaffected.
- **One more `hyprctl` call per keyboard line** (`layers -j`) beside #24's
  `activewindow`. Measured on razer when the plan is written; #24 measured
  `activewindow` at 0.01 s.

## Verification

Unit tests beside `tests/test_verified_input.py`, with `host` stubbed:

1. A layer target, mapped, no window focused, alone at its level →
   keystrokes sent, result names it.
2. The same with a window focused → refused, nothing sent.
3. Another layer at the same level, and one at a higher level → refused.
4. The address not mapped (closed, reopened elsewhere) → refused.
5. `layers -j` failing → `unavailable`, not success.
6. A condition changing mid-batch → the rest not sent (as #24's
   `test_focus_moving_mid_batch_stops_the_rest`).
7. A window target is unchanged: every existing #24 test passes as is.
8. CLI: `input --window 0x… '[key]'` reaches `run_batch` with `window`
   set; without it, the existing refusal.

On razer: open nixarchy-pkg's panel, `windows` lists
`nixarchy-pkg-menu` under `layers`, then `input --window <that address>`
with `j` moves the cursor, and the same with a toast up at overlay
refuses. With that working, the nixarchy-pkg keyboard checks (#27–#30)
can finally be run by an agent.
