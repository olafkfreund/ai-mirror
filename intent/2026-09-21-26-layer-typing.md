---
status: approved
issue: 26
author: olafkfreund
---

# Intent: typing into a shell surface, and typing from the CLI

## Problem

#24 made every keystroke name the window it is meant for, and refuses
unless `hyprctl activewindow` is exactly that window (`_require_focus`,
`control.py:378`). For windows that is right: it's what stops a keystroke
landing somewhere nobody chose.

It leaves two things that can't be done at all.

**A layer-shell surface can't be typed into.** The Omarchy menu, plugin
panels and launchers are layer surfaces that take the keyboard
exclusively. While one does, Hyprland reports focus as *no window*, so
there is no `window` an agent can name that passes the check:

    stale_generation: focus is no window, not 0x5efa8e6b4d30; input was NOT sent.

Found driving nixarchy-pkg's panel on razer. The agent could open the
panel (pointer actions still work) and read it, but couldn't press one
key in it. `index` lists the keys that open these surfaces, so the tool
leads an agent to exactly the place it then can't act.

**The CLI can't type anything.** `ai-mirror input` takes `--generation`
and the actions, with no way to name a window. Since #24 requires one for
every keyboard action, the CLI can click and nothing else.

## Proposed outcome

- An agent can type into a layer surface that has the keyboard, by naming
  that surface, with the same guarantee #24 gives windows: the keystroke
  lands only if the named target is what holds the keyboard at that
  moment, and is refused, and says why, otherwise.
- `ai-mirror input` can name its target, window or surface, so the CLI can
  do everything the MCP tool does.
- Nothing about typing into windows gets weaker.

## Affected users and systems

- Agents driving Omarchy/Quickshell surfaces over MCP or the CLI.
- `src/ai_mirror/control.py` (`_require_focus`, `run_batch`), `api.py`
  (the `input` op), `cli.py` (the `input` parser), `input.py` if the
  target shape changes, and `host.py` for reading layers.
- `index`, which should say how to target a surface.
- Tests beside #24's.

## Constraints

- **#24's guarantee stays positive by construction.** One value proceeds;
  "could not tell" never becomes "nothing is wrong".
- A surface must be identified by something the agent observed, not by
  "whatever layer has the keyboard now". The latter is exactly the
  unnamed target #24 exists to refuse.
- No new dependency. `hyprctl layers -j` is already available; whether it
  can say which layer holds the keyboard is for the spec to measure.

## Open questions

1. **What names a surface?** Its layer namespace (`nixarchy-pkg-menu`)
   plus monitor, from `hyprctl layers -j`, or an address if Hyprland gives
   layers one? A namespace is stable and readable; an address is exact.
2. **How is "this surface holds the keyboard" established?** Hyprland
   reports no focused layer directly. Candidates: the surface is mapped
   with exclusive keyboard interactivity and no window is focused, or a
   Hyprland event stream. The spec should measure which is positive
   rather than inferred.
3. **One `window` parameter taking both, or a separate `surface`?** One is
   simpler for callers; two keeps the #24 path untouched.
