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

## A grant belongs to whoever took it

More than one agent on one desktop is the normal case here, so a grant records
its holder (#40). Your server ending releases only your own grant; `control
off` from an agent that does not hold it answers `not_owner` and names the
holder's pid. A grant taken over the CLI outlives every server. A holder that
is no longer running holds nothing, so any agent may release it.

None of this applies to the person at the keyboard: the bar widget,
`Super + Shift + Escape` and `control off` from a terminal always work.

## The bar expands under a hovering cursor

Resting the pointer on the top bar expands the system tray, which shifts every
widget to its right. Coordinates measured a moment earlier are then wrong, and
nothing announces it.

**Do:** drive panels by their keybinding. If a click is unavoidable, keep the
pointer off the bar between clicks and re-measure after any hover.

## `Return` in the package panel writes to your configuration

`nixarchy.pkg` edits `~/.config/nixarchy/apps.nix` or `services.nix` at once.
`Return` on a boolean row toggles it with no confirmation, and "queued" looks
like UI state, not a file write. Two edits landed in one session:
`chrome.enable = true` and a *removal* of `azure-cli`. Neither was applied;
both had to be found and undone.

**Do:** check `nixarchy-pkg pending` before and after; snapshot those two files
around a scripted run and restore them if changed. Prefer a path option (its
editor cancels on Escape) over a boolean (toggles on `Return`).

## `input` returning does not mean anything happened

It reports the keystroke was delivered, nothing more. Measured: the call
returned at 164 ms and the panel it opened did not exist until 225 ms. A
sequence that types in that window types into whatever was behind.

**Do:** `ai-mirror wait --layer nixarchy-pkg-menu` after the key; continue only
on `confirmed`. `--absent` waits for a panel to close before opening the next,
since panels do not stack.

`not_confirmed` means it did not hold before the deadline, **not** that the
action failed: it may still land, and retrying can toggle shut the panel that
just opened. `unavailable` means the state could not be read: nothing learned.

It confirms a state, not a cause: another agent or the human can satisfy the
same predicate, and it can stop holding before your next action.

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

`screenshot` raises `sensitive` when a password manager, credential prompt,
private browsing window or banking page is visible anywhere in the captured
rectangle, not just when focused. The refusal names the kind, never the title.

The accessibility tools are guarded the same way: `a11y_tree` reports such a
window as `withheld` with no name and does not read inside it, `a11y_find`
cannot match there and says so, `a11y_act` refuses an id within one. A tree is machine-readable text, so
`a11y_find` is no way round a refused screenshot.

**Do:** capture a narrower region that excludes it, or ask the user to close
it. Best-effort: it matches on window class and title, so it misses things and
misfires. It does not make a screen safe to photograph.

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

Per-app results (what each action did in GTK4, Chrome, Firefox): `index --section measured`.

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

Layer surfaces, not windows. Hyprland 0.56.0 cannot say which holds the
keyboard (`layers -j`: `address, alpha, h, namespace, pid, w, x, y`), and
`activewindow` names the window *underneath*, so it is inferred from what is
mapped (#29).

**Do:** open it, call `windows`, pass its address from `layers` as `window`.
Accepted when it is topmost, on any monitor; a still-focused window is named in
the note, since keys go there if the surface does not take them. Refused while
another surface is at the same level or above (a notification over a menu):
wait and retry.

**Typing at a *window*** is refused while a level 2+ surface outside the exempt
set is up: it may hold the keyboard, and naming the window as destination then
is the failure this guards. The set starts as what was mapped at the grant and
**shrinks whenever a check finds one gone**: the confirm dialog and notifications
are surfaces too (#39). Checks run only on window-addressed calls, so a quick
leave-and-return goes unseen. The refusal says "opened since control was
granted" or "went away and came back".

A shell restart (`omarchy-restart-shell`) usually passes unnoticed (measured on
razer). If a check lands while the bar is down, it returns as "came back" and
input is refused until control is re-taken. Deliberate: admitting whatever
returns would reopen the hole for anything that can be made to flicker.

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

## Chrome ignores the middle mouse button

Delivered fine: `wev` shows `button: 274 (middle)`, press/release 5 ms apart,
and alacritty pastes the primary selection. Chrome ignores it on tabs and links
while `left`/`right` work (#37). GNOME apps never paste on middle click
(`gtk-enable-primary-paste = false`). `input` says `ok` either way: delivered.

**Do:** in Chrome, `CTRL+W` for a tab, `CTRL+click` for a background tab.

## What you launch dies with your terminal

`launch` children share the MCP server's systemd scope, which is its
terminal's (measured: tmux, foot). Close that terminal and they go too.

**Do:** `["uwsm-app", "--", "<app>", …]` gives each app its own scope, as
`omarchy-launch-*` do. `launch` does not add it for you.
