---
status: approved
issue: 78
spec: spec/2026-10-26-78-agent-cursor-frame.md
---

# Plan: you can see an agent is in control without looking at the bar

## Approved decisions (from the spec)

1. **The cursor theme is `ai-mirror-agent`, built from committed PNGs.**
   Three images in `cursor/`: arrow, hand and text. Each is the shape plus a
   red rounded "Agent" box below-right, no more than 64x40, nominal size 24.
   `xcursorgen` runs at build time only. Measured on this host: Hyprland
   0.56 draws a 72x40 image 1:1, and a symlinked theme directory loads.
2. **No `Inherits=` in `index.theme`.** Measured: with
   `Inherits=Bibata-Modern-Classic`, Bibata's shapes win, even over ones we
   define. So every shape is badged. Hand names map to the hand, text names
   to the I-beam, and every other name to the arrow.
3. **Install via Home Manager.** `home.file.".local/share/icons/ai-mirror-agent"`,
   for both the Nixarchy and the plain plugin route. The theme lives in its
   own package, `packages.cursor`, never in the plugin directory.
4. **`plugin/Overlay.qml` switches the cursor.** It runs fixed argv
   `hyprctl setcursor <theme> <size>`: `ai-mirror-agent` while
   `state.owner === "agent"`, otherwise
   `$HYPRCURSOR_THEME || $XCURSOR_THEME`. Size is `$XCURSOR_SIZE || 24`. It
   applies whenever the wanted value differs from the last one applied,
   starting from empty, so every shell start applies once and clears a
   stuck badge.
5. **The frame is always mapped, at `WlrLayer.Top`.** Namespace
   `omarchy-ai-mirror-frame`, `mask: Region {}`, `WlrKeyboardFocus.None`,
   `ExclusionMode.Ignore`, no `visible:` binding. Only the border shows the
   state: `border.width: root.agent ? 4 : 0`, colour `Commons.Color.urgent`.
   Being mapped before any grant puts it in `baseline_layers`, so
   `_refuse_new_surfaces` (`control.py:621`) never sees it as new. At level
   2, the bar's level, it adds no rival to `_require_layer` (`:679`). It
   hides under fullscreen windows; there the cursor badge is the indicator.
6. **Nothing in `api.py`, `control.py`, `mcp.py`, the CLI or the helper
   changes.** Both indicators are display only.
7. **Not shown while `owner` is `pending`.**

One detail the spec left open: `xcursorgen` builds one cursor file per
config, so `cursor/` holds three `.cfg` files (`arrow.cfg`, `hand.cfg`,
`text.cfg`) rather than one `agent.cfg`.

## Steps

1. **`cursor/` (new): art and xcursorgen configs.**
   Create the three 64x40 PNGs with ImageMagick (`magick` is on this host's
   PATH; the art is our own, not derived from Bibata, which is GPL). Run
   from the repo root:

   ```sh
   mkdir -p cursor && cd cursor
   B='-fill #d7263d -stroke white -strokewidth 1 -draw "roundrectangle 13,21 62,38 4,4" -fill white -stroke none -font DejaVu-Sans-Bold -pointsize 12 -annotate +16+34 Agent'
   eval magick -size 64x40 xc:none -fill white -stroke black -strokewidth 1.5 \
     -draw '"polygon 1,1 1,19 6,15 9,22 12,21 9,14 15,14"' $B -define png:bit-depth=8 arrow.png
   eval magick -size 64x40 xc:none -fill white -stroke black -strokewidth 1.5 \
     -draw '"polygon 6,1 9,1 9,8 15,9 15,18 12,21 6,21 2,14 4,12 6,14"' $B -define png:bit-depth=8 hand.png
   eval magick -size 64x40 xc:none -stroke black -strokewidth 3 -draw '"line 7,2 7,18 line 3,2 11,2 line 3,18 11,18"' \
     -stroke white -strokewidth 1 -draw '"line 7,2 7,18 line 3,2 11,2 line 3,18 11,18"' $B -define png:bit-depth=8 text.png
   printf '24 1 1 arrow.png\n'  > arrow.cfg
   printf '24 7 1 hand.png\n'   > hand.cfg
   printf '24 7 10 text.png\n'  > text.cfg
   ```

   Deviation (done): the `eval … $B` form fails on quoting ("missing output
   filename `-fill`"), so the same arguments were run with `$B` as a bash
   array. ImageMagick then wrote colormap PNGs, so each was rewritten with
   `magick X.png PNG32:X.png` to get RGBA. Coordinates and hotspots are
   unchanged.

   Verify: `file cursor/*.png` shows 64 x 40 RGBA. Open each scaled up 4x
   and check that the shape and the "Agent" text are legible and the text
   stays inside the box. Adjust the coordinates if not.
   Traps: no symlinks in `cursor/` (keep the source tree plain). Only the
   built package carries symlinks.

2. **`flake.nix`: the `cursor` package, install and checks.**
   - After `plugin = …;` (`:59-64`), add:

     ```nix
     # No Inherits: measured on Hyprland 0.56, an inherited theme's shapes win over ours (#78).
     cursor = pkgs.runCommand "ai-mirror-cursor-${version}" { nativeBuildInputs = [ pkgs.xcursorgen ]; } ''
       t=$out/share/icons/ai-mirror-agent
       mkdir -p $t/cursors
       printf '[Icon Theme]\nName=ai-mirror-agent\nComment=ai-mirror: an agent controls this desktop\n' > $t/index.theme
       cd ${./cursor}
       xcursorgen arrow.cfg $t/cursors/default
       xcursorgen hand.cfg $t/cursors/pointer
       xcursorgen text.cfg $t/cursors/text
       cd $t/cursors
       for n in hand1 hand2 pointing_hand; do ln -s pointer $n; done
       for n in xterm ibeam vertical-text; do ln -s text $n; done
       for n in left_ptr arrow top_left_arrow context-menu help progress wait watch left_ptr_watch \
                crosshair cell move all-scroll grab grabbing fleur not-allowed no-drop alias copy \
                col-resize row-resize n-resize e-resize s-resize w-resize ne-resize nw-resize \
                se-resize sw-resize ew-resize ns-resize nesw-resize nwse-resize zoom-in zoom-out; do
         ln -s default $n
       done
       ${licenceFiles}
     '';
     ```

   - `packages.${system}` (`:67`): add `cursor`.
   - Home Manager module, first block of `lib.mkMerge` (`:89-95`): add
     `home.file.".local/share/icons/ai-mirror-agent".source = "${cursor}/share/icons/ai-mirror-agent";`
   - `checks.licence` loop (`:123`): add `${cursor}`.
   - `checks`: add

     ```nix
     cursor = pkgs.runCommand "ai-mirror-cursor-check" { } ''
       t=${cursor}/share/icons/ai-mirror-agent
       for c in default pointer text left_ptr hand2 xterm; do test -e $t/cursors/$c; done
       grep -qx 'Name=ai-mirror-agent' $t/index.theme
       ! grep -q Inherits $t/index.theme
       touch $out
     '';
     ```

   Verify: `nix build .#cursor` succeeds, `ls -l result/share/icons/ai-mirror-agent/cursors`
   shows three files and the symlinks, and `nix flake check` is green.
   Traps: `./cursor` must be `git add`ed before the flake can see it. Don't
   put the theme in `plugin` (the `checks.plugin` symlink test would fail).

3. **`plugin/Overlay.qml`: cursor switch and frame.**
   - Imports: add `import Quickshell.Wayland` and `import qs.Commons as Commons`.
   - In `Item { id: root`, after `readonly property bool pending` (`:14`):

     ```qml
     // Display only, like the bar: state.json is the gate, these just follow it (#78).
     readonly property bool agent: state !== null && state.owner === "agent"
     readonly property string cursorSize: Quickshell.env("XCURSOR_SIZE") || "24"
     readonly property var wantedCursor: [agent ? "ai-mirror-agent"
         : (Quickshell.env("HYPRCURSOR_THEME") || Quickshell.env("XCURSOR_THEME") || "default"), cursorSize]
     // Starts empty so a shell start always applies once: clears a badge a dead shell left.
     property string appliedCursor: ""
     function applyCursor() {
       var key = wantedCursor.join(" ")
       if (key === appliedCursor || setcursor.running) return
       appliedCursor = key
       setcursor.command = ["hyprctl", "setcursor"].concat(wantedCursor)
       setcursor.running = true
     }
     onWantedCursorChanged: applyCursor()
     Component.onCompleted: applyCursor()
     ```

   - Below the `FileView`:

     ```qml
     // Re-checks on exit: a change that arrived while hyprctl ran is applied now.
     Process { id: setcursor; onExited: root.applyCursor() }

     // Always mapped, so a grant records it as furniture (baseline_layers) and
     // _refuse_new_surfaces never calls it new; Top, the bar's level, so it is
     // no rival _require_layer did not already have (#78). Only the border follows the state.
     Variants {
       model: Quickshell.screens
       PanelWindow {
         required property var modelData
         screen: modelData
         anchors { top: true; bottom: true; left: true; right: true }
         color: "transparent"
         exclusionMode: ExclusionMode.Ignore
         mask: Region {}
         WlrLayershell.namespace: "omarchy-ai-mirror-frame"
         WlrLayershell.layer: WlrLayer.Top
         WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
         Rectangle {
           anchors.fill: parent
           color: "transparent"
           border.width: root.agent ? 4 : 0
           border.color: Commons.Color.urgent
         }
       }
     }
     ```

   Verify: `nix build .#plugin` and `nix flake check` (`checks.plugin`) are
   green. The QML is checked live in step 6.
   Traps: no `visible:` on the `PanelWindow` (unmapping it breaks the
   input gate). No `dispatch`. No free-form string reaches hyprctl. The
   `@ai-mirror@` substitution only touches `AgentCommand.qml`; leave it.

4. **`tests/test_agent_indicator.py` (new).** Text assertions in the style
   of `tests/test_confirm_wiring.py`, stdlib only, no desktop:
   - `Overlay.qml` contains `"hyprctl", "setcursor"` and `"ai-mirror-agent"`,
     and does not contain `dispatch`.
   - `Overlay.qml` contains `Component.onCompleted: applyCursor()` and
     `appliedCursor: ""` (the first-run restore).
   - The frame block (from `Variants {` on) contains `mask: Region {}`,
     `WlrKeyboardFocus.None`, `WlrLayer.Top`, `border.width: root.agent ? 4 : 0`,
     and **no** `visible:`. Name this test after the gate it protects:
     `test_frame_stays_mapped_for_the_input_gate`.
   - Each `cursor/*.cfg` has one line `24 x y file`. The file exists, and
     its PNG IHDR (bytes 16-24, big-endian width and height) is no more
     than 64x40, with the hotspot inside it.
   - `cursor/` contains no symlinks.

   Verify: `python3 -m unittest tests.test_agent_indicator -v` passes, and
   `python3 -m unittest discover -s tests -v` stays fully green.
   Traps: `Base`/`guard` aren't needed (nothing here reaches a seam), but
   don't import anything that touches the desktop.

5. **Docs.**
   - `docs/usage.md` "Control model" (after the `watching` bullet, about
     `:18-19`): one bullet. While `owner` is `agent`, the cursor carries an
     "Agent" badge and every monitor shows a red frame. Both follow
     `state.json` and are display only, not part of the gate. The frame
     hides under fullscreen windows, where the badge still shows.
   - `docs/usage.md` Troubleshooting (end, about `:143`): "Badge or frame
     stuck, or missing: both are drawn by the shell; restart it, and the
     first state read restores your cursor. The theme is installed by the
     Home Manager module."
   - `AGENTS.md` code map: add a `cursor/` row ("Agent cursor art +
     xcursorgen configs; built into `packages.cursor`, no `Inherits` (#78)")
     and extend the `plugin/Overlay.qml` row with "switches the cursor theme
     and draws the frame".
   - `AGENTS.md` Invariants: add "**The frame surface is always mapped.**
     Only its border follows the owner. A frame that maps at the grant is a
     new surface to `_refuse_new_surfaces` and refuses all typing (#78)."

   Verify: read the rendered diff. `nix flake check` is still green.

6. **Live check on this host (Claude with the user; not the coder).**
   Apply the Home Manager change and restart the shell. Then:
   1. `ai-mirror control agent`, approve with **A**. The badge shows over
      plain desktop, a link and a text field, and the red frame shows on
      DP-1, DP-3 and HDMI-A-1.
   2. Type into a window:
      `ai-mirror input --generation N --window <addr> '[{"type":"type","text":"x"}]'`.
      Not refused with `wrong_target`.
   3. Clicks pass through the frame at a screen edge.
   4. `Super+Shift+Escape`: badge and frame gone, Bibata back at 24.
   5. Grant again, restart the shell, `control off`: no stuck badge.

   Traps: the shell environment of this Claude session has a stale
   `HYPRLAND_INSTANCE_SIGNATURE`. Export the newest one from
   `/run/user/1000/hypr/` before any `hyprctl` call.

## Tests

```sh
python3 -m unittest discover -s tests -v   # all green, including test_agent_indicator
nix flake check                            # unittest, confirm-keys, licence, plugin, cursor
nix build .#ai-mirror .#ai-mirror-input .#plugin .#cursor
```

Then step 6 by hand.

## Rollback

Revert the branch's commits. If a badge is stuck on a machine afterwards:

```sh
hyprctl setcursor "$XCURSOR_THEME" "${XCURSOR_SIZE:-24}"
```

Nothing in the state file or the gate changed, so there is no data to
migrate.
