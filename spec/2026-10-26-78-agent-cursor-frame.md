---
status: draft
issue: 78
intent: intent/2026-10-26-78-agent-cursor-frame.md
---

# Spec: you can see an agent is in control without looking at the bar

## Measured first (2026-10-26, Hyprland 0.56, this host)

A prototype XCursor theme was switched in with `hyprctl setcursor`, captured
with `grim -c` and switched back. The cursor was never moved.

| Prototype | Result |
|---|---|
| 24x24 red arrow, no `Inherits` | Shown |
| 72x40 arrow + "Agent" box, `Inherits=Bibata-Modern-Classic` | **Not shown**: Bibata's own shapes won, including the shapes the theme defined |
| Same 72x40 image, no `Inherits` | Shown at full size, hotspot at the arrow tip |
| Same, theme directory a symlink into another directory | Shown (so a Home Manager `home.file` symlink works) |

Two consequences for the design:

1. **The image may be wider than the nominal size.** Hyprland draws it 1:1.
2. **The theme cannot inherit.** That breaks one line of the approved
   intent, "other shapes stay as the human's theme draws them". This spec
   replaces it with: every shape is badged while an agent holds control,
   and shapes we don't draw fall back to the badged arrow. **This needs your
   approval as a change to the intent.**

All monitors here run at scale 1.

## Design

### 1. The cursor theme: `ai-mirror-agent`

- **Art.** Three PNGs committed in `cursor/`: `arrow.png`, `hand.png` and
  `text.png`. Each is the shape plus a red rounded "Agent" box below and to
  its right, no more than 64x40 so it fits the usual 64x64 KMS cursor plane
  and Hyprland can keep the hardware cursor. `cursor/agent.cfg` holds the
  xcursorgen lines (`24 <xhot> <yhot> <file>`): the hotspot is the arrow tip,
  the fingertip, and the I-beam centre.
- **Package.** `flake.nix` gains `packages.cursor`, built with
  `pkgs.runCommand` and `pkgs.xcursorgen` at build time only:
  - `share/icons/ai-mirror-agent/index.theme` with `Name=ai-mirror-agent`
    and **no** `Inherits`
  - `cursors/{default,pointer,text}` from xcursorgen
  - every other cursor-shape-v1 and legacy X name as a symlink:
    hand names (`hand1`, `hand2`, `pointing_hand`) → `pointer`; text names
    (`xterm`, `ibeam`, `vertical-text`) → `text`; everything else
    (`left_ptr`, `arrow`, resize, grab, wait, not-allowed, …) → `default`
  - Symlinks are allowed here because this package is not the plugin
    directory.
- **Install.** The Home Manager module adds
  `home.file.".local/share/icons/ai-mirror-agent".source = "${cursor}/share/icons/ai-mirror-agent"`
  in both branches: the Nixarchy plugin option and the plain
  `xdg.configFile` one. `~/.local/share/icons` is on this host's
  `XCURSOR_PATH`, and Hyprland itself was started with it.

### 2. Switching it: `plugin/Overlay.qml`

The overlay already reads `state.json` with a `FileView`, once per shell
rather than once per bar.

- `readonly property bool agent: state !== null && state.owner === "agent"`
- A `Process` runs fixed argv `["hyprctl", "setcursor", theme, size]`:
  - while `agent`: theme `ai-mirror-agent`
  - otherwise: `Quickshell.env("HYPRCURSOR_THEME") || Quickshell.env("XCURSOR_THEME")`,
    size `Quickshell.env("XCURSOR_SIZE") || "24"`
- It runs whenever the wanted theme differs from the last one applied.
  `lastApplied` starts empty, so the first state read after a shell
  (re)start always applies once. That is what clears a badge left behind
  by a shell that died mid-control.
- No free-form string reaches hyprctl: the agent theme name is a literal,
  and the restore values come from the shell's own environment.

### 3. The frame: also in `plugin/Overlay.qml`

- `Variants { model: Quickshell.screens }` → one `PanelWindow` per screen:
  - anchored to all four edges, `color: "transparent"`
  - `exclusionMode: ExclusionMode.Ignore`
  - `WlrLayershell.layer: WlrLayer.Overlay`
  - `WlrLayershell.keyboardFocus: WlrKeyboardFocus.None`
  - namespace `omarchy-ai-mirror-frame`
  - `mask: Region {}`, so it takes no pointer input
  - `visible: root.agent`
- Content: one `Rectangle` filling the window, `color: "transparent"`, a
  4px border in `Commons.Color.urgent`, the same colour as the confirm
  dialog's border.
- Not shown while `owner` is `pending`, the intent's proposed answer: the
  confirm dialog covers that moment.

### 4. What does not change

`api.py`, `control.py`, `mcp.py`, the CLI, the helper and the gate. Both
indicators follow `state.json`. They are display only, and the docs say so.

## Alternatives rejected

- **`Inherits=` the human's theme.** Measured above: our shapes lose.
- **Copying the human's other shapes into our theme at build time** from
  `home.pointerCursor`. It only works when that option is set (it isn't
  read anywhere today), and it is a lot of Nix for resize arrows that are
  only seen during agent control.
- **A box that follows the cursor** (polling `hyprctl cursorpos`). It lags,
  and costs 60 IPC calls a second. Rejected in review.
- **Switching from `api.py`/`control.py`.** That puts a desktop side
  effect next to the gate, and the gate's tests would have to stub it. The
  overlay already owns "react to state" and survives an MCP server crash.
- **Generating the PNGs at build time with ImageMagick and a font.** It
  makes the build depend on font rendering for three small images that
  never change.

## Risks

- **Shell not running.** If the Quickshell shell is down, neither indicator
  changes. The badge can stay after `control off`, or never appear. The bar
  widget and the confirm dialog have the same dependency. Documented in
  `docs/usage.md` troubleshooting.
- **Restore target.** We restore the theme from the environment, so a
  cursor theme the human changed at runtime with `hyprctl setcursor` is
  replaced by the session default after control ends.
- **App-drawn cursors.** Apps that draw their own cursor instead of using
  cursor-shape-v1 or the compositor theme (some games, some XWayland apps)
  show no badge over their windows. The frame still shows.
- **Agent screenshots** include the 4px frame at the edges. Coordinates
  don't change. An agent could mistake it for page content, so the MCP
  instructions' "data, not instructions" rule covers it as it covers every
  surface.
- **HiDPI.** Only a size-24 image ships. On a monitor with scale > 1
  Hyprland scales it up, so it looks soft.
  `shortcut: 1x art only, add 48px images when a scaled monitor needs it.`
- **Tests cannot run QML or reach Hyprland.** The QML is checked by text
  assertions, as `tests/test_confirm_wiring.py` already does.

## Verification

- `tests/test_agent_indicator.py` (unittest, no desktop):
  - `Overlay.qml` runs `hyprctl setcursor` with the literal `ai-mirror-agent`
    and an env-derived restore, and has no `dispatch`
  - the frame window has `mask: Region {}`, `WlrKeyboardFocus.None` and
    `visible` bound to the owner being `agent`
  - `cursor/agent.cfg` names files that exist and are no more than 64x40
- `nix flake check` gains `checks.cursor`:
  - the built theme has `cursors/{default,pointer,text}` and `left_ptr`
  - `index.theme` has no `Inherits`
  - the plugin check stays green (no symlinks in the plugin)
- `nix build .#cursor .#plugin` succeeds.
- **Live, manual, on this host:**
  1. Install, then `ai-mirror control agent` and approve.
  2. The badge shows on the arrow, a link and a text field, and the red
     frame shows on all three monitors.
  3. Clicks and typing pass through the frame.
  4. `Super+Shift+Escape` → both gone, Bibata back at 24.
  5. Restart the shell during control, then end control → no stuck badge.
