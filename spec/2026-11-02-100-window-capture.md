---
status: approved
issue: 100
intent: intent/2026-11-02-100-window-capture.md
---

# Spec: capture one window, including one on a hidden workspace

## Design

One new argument, `window`, on the existing `screenshot`. No new tool.

### `src/ai_mirror/host.py`

`windows()` adds `stableId` to the keys it keeps (`hyprctl clients -j` reports
it; measured `18000005`). It is the identifier `grim -T` takes.

### `src/ai_mirror/control.py`, `screenshot(dest, output, region, max_size, window=None)`

When `window` is given (mutually exclusive with `output`/`region`, else
`ValueError`):

1. Look the address up in `host.windows()`. Not found, or no `stableId` →
   `MirrorError('invalid', 'no window <addr>; call windows')`. The address and
   the `stableId` reach grim only after this lookup, so caller text never reaches
   the argv; `stableId` is additionally checked to be hex (`[0-9a-f]+`).
2. **Privacy** (decision 2's guard): `privacy.kind(class, title)` on the window
   itself → `MirrorError('sensitive', …)`, wording as today's refusal. The
   rectangle check `privacy.refuse` is not used: a toplevel capture contains
   only that window's pixels, so nothing beside or over it can leak in. The check
   runs whether or not its workspace is visible.
3. **On screen?** `visible = str(workspace) in host.visible_workspaces()`.
   `region = [*at, *size]`.
   `view_only` is true when the workspace is not visible (decision 1), **or**
   when another window on a visible workspace intersects the box
   (`privacy.covering` minus the window itself). Where windows overlap, the
   window's own buffer differs from what is on screen, so a click mapped from
   it could land on the other window. `note` says which reason applies.
4. `grim -T <stableId> [-s scale] dest`, with `stdin=DEVNULL`, the same timeout,
   error handling and PNG-size read as today. `max_size` scales the same way,
   from the window's `size`.
5. Result: today's keys, with `region` the window's box and `output` its
   monitor, plus `window` (the address), `visible`, `view_only` and `note`.

### `src/ai_mirror/mcp.py`

- `screenshot` schema: `window: STR`; `observe` passes it through. The frame
  metadata adds `window`, `visible`, `view_only` and `note` when present.
- `from_frame`: a frame with `view_only` raises
  `MirrorError('invalid', 'frame <id> is a capture of window <addr> on a hidden
  workspace (or under another window): switch to it and take a fresh screenshot
  before acting')`. Nothing is sent.
- Tool description: "window = address from windows: that window only, even on a
  hidden workspace (view-only there)."

### `src/ai_mirror/cli.py`

`screenshot --window <address>`.

### Docs

`docs/usage.md` screenshot row: the `window` argument, `view_only`, and the
privacy refusal on the window itself.

## Alternatives rejected

- **A separate `window_screenshot` tool.** The same frame machinery and
  privacy step; one argument is smaller and reads the same to an agent.
- **Crop a monitor capture to the window box.** It brings in whatever overlaps
  the window, and cannot reach a hidden workspace, which is the point of #100.
- **Always view-only** (the intent's alternative). Rejected by decision 1.
- **Use the frame even when another window overlaps it.** A click would map
  from pixels that are not on screen there. Overlap is rare with tiling but
  common with floating dialogs, so it is checked.
- **Checking layer surfaces over the window too.** The frame overlay
  (`omarchy-ai-mirror-frame`, level 2) covers every monitor, so a box-based check
  would mark every window capture view-only. Keyboard input over a surface
  stays guarded by `_refuse_new_surfaces`. A click under a panel that opened
  after the capture is the same stale-frame case as with a monitor screenshot.

## Risks

- **grim without `-T`** (older grim): `grim failed: …` becomes `unavailable` as
  today, with grim's own message. p620 and razer have it.
- **`stableId` absent** on an older Hyprland: `invalid` from step 1. Only ≥ 0.56
  is supported here.
- **Privacy matching misses** a private window whose class and title don't match:
  the same limit as today's refusal, and the existing message says so.
- **A hidden window may render stale** (a client that stops drawing while
  unseen). It is still that window's own last buffer; nothing else leaks in.

## Verification

- Unit tests, with grim and `host` stubbed:
  - argv is `grim -T <stableId> dest`, plus `-s` when scaled; never the caller's
    string;
  - an unknown address, or a non-hex `stableId`, gives `invalid` and runs no grim;
  - a private window gives `sensitive` and runs no grim, on a visible and on a
    hidden workspace;
  - visible and not overlapped gives `view_only: false` and `region` = its box;
    hidden gives `view_only: true`; overlapped by another visible window gives
    `view_only: true`, with the note;
  - `window` together with `output` or `region` gives `ValueError`;
  - `from_frame` on a view-only frame gives `invalid` and sends no input;
  - the CLI parses `screenshot --window`.
- `nix flake check`; `nix build .#ai-mirror`.
- Live on p620: capture a visible window. The PNG matches its `size`, and an
  `input` move with that frame maps to its box. Capture a window on a hidden
  workspace: `view_only: true`, the image shows the window, and the focused
  workspace has not changed. `input` with that frame gives `invalid`.
