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

The accessibility tools are guarded the same way: `a11y_tree` reports such a window as
`withheld` with no name and does not read inside it, `a11y_find` cannot match there and says
so, and `a11y_act` refuses an id within one. A tree is machine-readable text, so reaching for
`a11y_find` is not a way round a refused screenshot.

**Do:** capture a narrower region that excludes it, or ask the user to close it. Treat this
as best-effort: it matches on window class and title, so it misses things and it misfires.
It does not make a screen safe to photograph.

## `doctor` and a shell with no desktop session

Every subcommand goes through Hyprland, so a non-login shell — ssh, a systemd
unit, a cron job — fails at all of them with `HYPRLAND_INSTANCE_SIGNATURE not
set`. `doctor` now says so instead of reporting `ok` (#32); it names the unset
variables, and `demo/rz` in this repository is a worked example of exporting
them from the running session.

## Accessibility trees are per-application, and mostly absent

quickshell exposes none, so bar and plugin panels are keyboard-only. Native GTK
apps do expose trees; Chromium and Electron give only an application and a
frame unless launched with `--force-renderer-accessibility` (#13).

**Do:** read `content` in any a11y result -- false means there is nothing
there a caller can match by name or act on, not that the screen is empty, so
screenshot instead. GTK4 applications often expose only anonymous groupings,
which used to count as content and do not now (#33). `set_text` needs the
AT-SPI EditableText interface, which Chromium does not implement even where
it reports the `editable` state: focus the node, then send keystrokes. Keybindings
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

## Typing into a menu, panel or launcher

These are layer surfaces, not windows. Hyprland cannot say which surface holds
the keyboard — measured on 0.56.0, `layers -j` carries only `address, alpha,
h, namespace, pid, w, x, y` — and `activewindow` keeps naming the window
*underneath* an overlay that has taken the keys. So nothing can be asked; it
can only be inferred from what is mapped (#29).

**Do:** open it, call `windows`, and pass the surface's address from `layers`
as `window`. It is accepted when that surface is the topmost thing mapped, on
any monitor. A window that still holds focus no longer refuses the call: it is
named in the result note instead, because if the surface does not take the
keyboard, that window is where the keys went.

It is refused while another surface is open at the same level or above (a
notification over a menu, say): the message names it. Wait for it to go,
observe again, and retry.

**And the other way round:** typing at a *window* is refused while a surface
that was not mapped when control was granted is up at level 2 or above. That
surface may hold the keyboard, and reporting the window as the destination
when the keys went elsewhere is the failure this guard exists to prevent.
Wait for it to go, or address the surface directly.

## A refusal can mean part of the batch already landed

`input` delivers a batch line by line and rechecks focus before every line, so
a refusal partway through arrives *after* the earlier lines were delivered.
The error says so: `partial: 9 of 14 lines delivered (actions 1-2 of 3
completed), then ...`, with `delivered`, `of`, `actions_completed` and
`actions_total` alongside the message (#30).

**Do:** observe before retrying. Retrying a partial batch types the delivered
prefix a second time. Only when the message says `input was NOT sent`, with no
counts, did nothing land.

## `wrong_target` is not `stale_generation`

`wrong_target` means the thing you aimed at is not the one that can be typed
into — a different window has focus, or a surface is in the way. You still
have control: observe and aim again (#31).

`stale_generation` means control itself moved: the human took it back, or a
new grant was made. Stop and ask again.

## The middle mouse button does nothing

Measured on razer: `left`, `right`, `back` and `forward` all work; `middle` is
acked and has no effect in Chrome (closing a tab, opening a link in a new tab)
or in GTK (primary-selection paste). Every button goes through one identical
`zwlr_virtual_pointer_v1_button` call, so the loss is below this codebase and
nothing can observe it — `input` will report `ok` (#37).

**Do:** use a keyboard equivalent — `CTRL+W` for a tab, `CTRL+click` or the
context menu for a link.
