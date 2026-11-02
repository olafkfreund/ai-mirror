---
status: approved
issue: 100
author: olafkfreund
---

# Intent: capture one window, including one on a hidden workspace

## Problem

`screenshot` captures a whole output or a region of the screen. To look at one
window, an agent captures the monitor and crops, which brings in whatever else
is on screen (other windows, notifications, the bar). To look at a window on a
workspace nobody is viewing, it must switch workspace first. That moves the
person's view, and it is the on-screen churn `AGENTS.md` warns about when
recording. `ocr` refuses a window on a hidden workspace outright
(`api.py:300`, `invalid`).

Hyprland 0.56 can capture one window's own buffer directly. Measured on p620
(2026-11-02):

- `grim -T <id>` takes a foreign-toplevel identifier, which is the `stableId`
  `hyprctl clients -j` reports (`18000005` for herdr). It captured 2520×1384,
  exactly the window's `size`, in 0.14 s.
- During the #95 research it also captured a window on a hidden workspace.
- An unknown id gives `cannot find toplevel`, exit 1.
- The compositor advertises `ext_image_copy_capture_v1` and
  `ext_foreign_toplevel_image_capture_source_manager_v1`.

## Proposed outcome

- `screenshot` accepts `window: <address>` (from `windows`), and returns that
  window's pixels only, without other windows or the bar, whether or not its
  workspace is visible.
- The privacy refusal applies to the window itself. A private window
  (`privacy.kind` on its class and title) is refused (`sensitive`), as a screen
  capture over it is today, hidden workspace or not.
- The result says whether the window is on screen, so the agent knows whether it
  can act on what it sees.
- No workspace switch, focus change or other side effect.

## Affected users and systems

- `src/ai_mirror/control.py` (`screenshot`), `host.py` (address → `stableId`),
  `mcp.py` (schema and frames), `cli.py`, tests, `docs/usage.md`.
- Agents on Hyprland ≥ 0.56 with grim ≥ the version that has `-T` (p620, razer).

## Constraints

- **Input must never land on a window the person cannot see.** A capture of a
  hidden window is something to look at, not a frame to click into.
- The privacy refusal must not get weaker. A window capture shows only that
  window, so the refusal no longer has to consider what overlaps it on screen.
  But it must still refuse a private window, including one nobody is looking at.
- The address is validated before it reaches anything; `grim` gets argv, no
  shell, `DEVNULL` stdin (the "nothing inherits the MCP stdout" rule).
- No new dependency: `grim` is already used.
- Tests cannot reach the desktop: grim and hyprctl are stubbed.

## Decisions (approved 2026-11-02)

1. A capture of a window on a visible workspace is a normal frame: its pixels map
   to the window's place on screen and `input` may use it. A capture of a window
   on a hidden workspace is view-only: `input` with that frame is refused
   (`invalid`: switch to its workspace first).
2. No grant, same as `screenshot`; the privacy refusal is the guard.
3. `ocr` on a hidden window is out of scope (a follow-up).
