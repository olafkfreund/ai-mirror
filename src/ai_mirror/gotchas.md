# Gotchas

Things that bite an agent driving this desktop, why they happen, and what to do
instead. Every entry cost somebody a real failure.

Hand-written and human-reviewed. `index.py` only ever reads this file — nothing
generates or rewrites it. An agent that learns something new proposes a diff
like anyone else, because a wrong lesson recorded silently is worse than no
lesson at all.

## The bar expands under a hovering cursor

Resting the pointer on the top bar expands the system tray, which shifts every
widget to its right. Coordinates measured a moment earlier are then wrong, and
nothing announces it.

**Do:** drive panels by their keybinding. If a click is unavoidable, keep the
pointer off the bar between clicks and re-measure after any hover.

## `Return` in the package panel writes to your configuration

`nixarchy.pkg` queues a change by editing `~/.config/nixarchy/apps.nix` or
`services.nix` immediately. `Return` on a boolean row toggles it; there is no
confirmation step, and "queued" looks like a UI state rather than a file write.

Two edits landed this way during one session: `chrome.enable = true`, and a
*removal* of `azure-cli`. Neither was applied, both had to be found and undone.

**Do:** check `nixarchy-pkg pending` before and after. Snapshot those two files
around any scripted run and restore them if they changed. Prefer a path option,
whose editor cancels on Escape, over a boolean, which toggles on `Return`.

## Escape does not reliably close a shell panel

A focused search field swallows the first Escape, so the panel stays up — and
panels do not stack. A second Escape sent when nothing is open lands on whatever
is behind.

**Do:** `omarchy-shell -q shell hide <plugin-id>`. It names what it closes, is
idempotent, and is silent when that panel is not open, so it is safe to call
before every open.

## The shell cannot tell you what is on screen

`isOpen`, `visible`, `panels`, `activePanel`, `listOpen`, `openPanels` and
`status` all answer `Function not found`. `listPlugins` has an `active` field
whose meaning is unconfirmed. So "did that panel open, and which tab has focus?"
is answerable only by screenshot.

**Do:** prefer one call that cannot drift over a sequence of steps that can.
`omarchy-shell shell summon <id> <json>` passes a payload to the plugin, which
is the shape a caller wants even where plugins currently discard it. Tracked as
olafkfreund/nixarchy#749.

## QuickShell exposes no accessibility tree

`a11y-tree` returns `{"role":"application","name":"quickshell","states":[]}`
with no children. The bar and every plugin panel are therefore keyboard-only.
Electron and GTK applications do expose full trees with bounds and actions.

**Do:** `a11y_find` for ordinary applications; keybindings and keyboard
navigation for anything the shell draws. Never assume a11y covers the desktop
itself.

## Panels render on the focused monitor

A panel opens on whichever monitor has focus, not the one being recorded or
screenshotted. It is easy to open something correctly and photograph an empty
screen.

**Do:** `hyprctl dispatch 'hl.dsp.focus({ monitor = "DP-1" })'` immediately
before the keystroke.

## Hyprland 0.56 dispatches Lua

`hyprctl dispatch workspace 8` is a syntax error. The form is
`hyprctl dispatch 'hl.dsp.focus({ workspace = "8" })'`, and window matching is
`hl.dsp.window.move({ workspace = "8", window = "title:x" })`.

A dispatch that matches nothing still reports `ok`, so a window close can
silently do nothing.

**Do:** verify with `hyprctl clients -j`, or kill the process instead when the
target is one you started.

## herdr refuses to nest

A herdr session started from inside one dies with "nested herdr is disabled by
default" — which an agent running in a herdr pane hits constantly.

**Do:** strip `HERDR_ENV`, `HERDR_SESSION`, `HERDR_PANE_ID`, `HERDR_TAB_ID`,
`HERDR_SOCKET_PATH` and `HERDR_WORKSPACE_ID` from the child's environment.

## Before recording anything

- `omarchy-toggle-notification-silencing` — a personal notification will
  otherwise arrive mid-take. One did, showing a purchase receipt.
- Chrome needs `--user-data-dir=<scratch> --no-first-run`. The real profile puts
  the user's bookmarks bar across the top of every frame.
- Work on an empty workspace on a monitor the human is not using.

## `pkill -f` matches the shell that ran it

The pattern usually appears in the invoking command line too, so `pkill -f foo`
can kill its own shell. This wasted two runs before it was spotted.

**Do:** the bracket trick, `pkill -f "[f]oo"`, or match something unique such as
a scratch profile path, and never put the kill and the thing being killed in one
command line.
