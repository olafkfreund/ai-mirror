# Gotchas

Things that bite an agent driving this desktop, why they happen, and what to do
instead. Every entry cost somebody a real failure.

Hand-written and human-reviewed. `index.py` only ever reads this file — nothing
generates or rewrites it. An agent that learns something new proposes a diff
like anyone else, because a wrong lesson recorded silently is worse than no
lesson at all.

## Asking for control is not having it

`control agent` opens a dialog on the user's desktop and returns
`owner: pending`. Input stays refused until they answer. Poll `status`: `agent`
means yes, `off` means no or that nobody answered within 30 seconds.

**Do:** ask, poll, and if it comes back `off`, say so and stop. Asking twice
because the first attempt "failed" is asking a person who already said no.

**Also:** a grant ends by itself after ten minutes with no input. A long think
between actions can outlive it; expect `not_owner` and ask again rather than
retrying the input.

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

## `input` returning does not mean anything happened

It reports that the keystroke was delivered, nothing more. Measured here: the
call returned at 164 ms and the panel it opened did not exist until 225 ms. A
sequence that types in that window types into whatever was behind.

**Do:** `ai-mirror wait --layer nixarchy-pkg-menu` after pressing the key, and
only continue on `confirmed`. Use `--absent` to wait for a panel to close
before opening the next, since panels do not stack.

`not_confirmed` means it did not hold before the deadline — **not** that the
action failed. It may still land. Retrying on it can toggle shut the panel that
had just opened. `unavailable` is a third thing again: the state could not be
read, so nothing was learned either way.

It confirms a state, not a cause. Another agent or the human can satisfy the
same predicate, and a confirmed state can stop holding before the next action.

## Navigating the package panel

It opens with the *list* focused, not the search box — deliberately, so `l`
changes tab instead of typing an `l`. A caller that types a query straight after
opening has it eaten as single-key commands, which is how a tab count came to be
wrong and a `Return` landed on the wrong row.

**Do:** click the filter box before typing (`/` is supposed to focus it and did
not reliably). Then `Tab` and `Shift+Tab` cycle Apps → Services → Packages →
Options → Drafts; arrows or `j`/`k` move the cursor; `Return` opens the
selected row. Never send a bare `a`: it applies.

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

## Captures are refused over password managers and credential prompts

`screenshot` raises `sensitive` when a password manager, a credential prompt, a private
browsing window or a banking page is visible anywhere in the rectangle being captured --
not just when it has focus. The refusal names the kind and never the window title.

**Do:** capture a narrower region that excludes it, or ask the user to close it. Treat this
as best-effort: it matches on window class and title, so it misses things and it misfires.
It does not make a screen safe to photograph.

## Accessibility trees are per-application, and mostly absent

quickshell exposes none, so bar and plugin panels are keyboard-only. Native GTK
apps do expose trees; Chromium and Electron give only an application and a
frame unless launched with `--force-renderer-accessibility` (#13).

**Do:** read `content` in any a11y result -- false means the tree is
unavailable, not that the screen is empty, so screenshot instead. Keybindings
for anything the shell draws. Never assume a11y covers the desktop itself.

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
