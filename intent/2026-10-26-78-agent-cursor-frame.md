---
status: approved
issue: 78
author: olafkfreund
---

# Intent: you can see an agent is in control without looking at the bar

## Problem

While an agent holds control, the only sign on the desktop is the bar
widget: a 16px mark in one corner of one bar. Someone watching the screen,
the cursor or a fullscreen app does not see it. The agent moves the same
seat cursor the human uses, so a pointer moving on its own looks exactly
like a human moving it.

The cursor alone is not enough either: this host sets
`cursor.hide_on_key_press = true` (`~/.config/hypr/looknfeel.lua:88`), so
the cursor disappears while the agent types, and `a11y_act`, `window` and
`launch` change the desktop without moving the pointer at all.

## Proposed outcome

While `owner` is `agent`, and only then:

- the cursor carries a small box reading "Agent", attached below-right of
  the arrow, on the arrow, hand (link) and I-beam (text) shapes. Other
  shapes stay as the human's theme draws them. The click point is unchanged.
- every monitor shows a thin red frame at its edges, above fullscreen
  windows, that never takes clicks or keyboard focus.

When control ends by any route (`control off`, the kill switch, the
pending-request or idle expiry, the MCP server exiting) both disappear and
the human's own cursor theme and size are back. A shell restart shows the
state that is current, never a stale one.

The cursor is a premade image shipped as a cursor theme; nothing is drawn
per frame and nothing polls the cursor position.

## Affected users and systems

- Anyone running the ai-mirror plugin on Nixarchy/Omarchy with Hyprland.
- `plugin/Overlay.qml` (already watches the state file), `flake.nix`
  (a cursor-theme package), tests, `docs/usage.md`, `AGENTS.md`.
- No change to the MCP tools, the CLI, the ownership gate or the helper.

## Constraints

- Indicators are display only. They must never become part of the gate or
  be described as a safety boundary: the state file stays the truth.
- The plugin directory contains no symlinks; the cursor theme lives in its
  own Nix output.
- No new runtime dependencies; build-time tools from nixpkgs are fine.
- Must restore the human's cursor theme and size, not a hard-coded one.
- Tests cannot reach the desktop: no `hyprctl setcursor` from a test.
- Screenshots taken by the agent (`grim`) must not change because of the
  frame in a way that breaks coordinate frames.

## Open questions

- Should the frame also show while `owner` is `pending` (the human is being
  asked), e.g. in amber? Proposed: no, the confirm dialog already covers that.
- Does Hyprland draw a cursor image wider than its nominal size (the badge
  needs roughly 64x32 at size 24) without scaling it down? To be prototyped
  in the spec stage before the design is fixed.
