---
status: approved
issue: 88
author: olafkfreund
---

# Intent: typed text and the keys after it reach the window with a stale keymap

## Problem

An agent cannot type a command and press Enter. Measured on 2026-10-30 in a
`nixarchy-desktop` microvm (Hyprland `3633316`, ai-mirror 3.1.0), typing
`touch /mnt/host/<term>-<i>` then `RETURN`, three rounds per terminal:

| Typed by | foot | alacritty | kitty |
| --- | --- | --- | --- |
| ai-mirror MCP (one persistent helper) | 0/3 | 0/3 | 0/3 |
| ai-mirror CLI (a new helper per call) | 0/3, text right | | |
| `wtype` (a new keyboard per call) | 3/3 | | |

With the persistent helper, every round shows round 0's text (`foot-0` three
times) and no `RETURN` runs it. With a new helper per call the text is right
each round, but `RETURN` still does nothing.

`wev` in the same guest received every keymap and key in order, so the helper
sends the right thing. The window does not get it: Hyprland sends a keymap to
a client only when it differs from the last one it sent, and keeps that last
one as a `std::string_view` into the keyboard's own keymap string
(`src/protocols/core/Seat.cpp:375-382`). When the helper replaces its
keyboard's keymap, that view can alias the new string, so the change looks
like no change and is never sent. Why `wev` is spared is not explained.

`type` uploads a throwaway keymap for its characters and then restores the
default one, so it changes its keymap twice per call: every typed string and
the key after it depends on Hyprland noticing both.

## Proposed outcome

On the Hyprland nixarchy ships, an agent's `type` followed by `key RETURN`,
in one batch or two, lands the right text and runs it, every time, in foot,
alacritty and kitty. Measured the same way as above: 3/3 in each.

## Affected users and systems

- `src/ai_mirror_input/ai_mirror_input.c` (the `T` and `K` paths), maybe
  `src/ai_mirror/input.py`.
- Every agent typing through ai-mirror: the real desktop and the
  `hyprland-ai-mirror` and `nixarchy-desktop` microvm templates.
- Not yet measured on a real desktop: it needs the human to grant control.

## Constraints

- No new dependency; the helper stays one C file on libwayland and xkbcommon.
- The invariants hold: `C` releases every held key, stdin EOF releases and
  exits, `run_batch` acks every line.
- Unicode typing keeps working for characters the default keymap lacks.
- No change to Hyprland in this repo. Reporting the bug upstream is separate.

## Open questions

None. Decided at approval (2026-10-30):

1. Yes: report the `m_lastKeymap` aliasing to hyprwm/Hyprland once the fix
   here is measured.
2. Yes: verification includes one check on the real desktop, with the owner
   granting control.
