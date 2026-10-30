---
status: approved
issue: 92
author: olafkfreund
---

# Intent: drive a Windows PC through an RDP window

## Problem

The user wants ai-mirror to work on a remote Windows PC using only an RDP
session shown on this desktop: read the session's pixels, drive this
machine's cursor and keyboard into it. Nothing may be installed or run on
the Windows PC.

An RDP client (xfreerdp 3.32, wlfreerdp, Remmina are installed) is one more
Hyprland window, so the pieces are mostly there, but three gaps remain:

1. **No structured view of Windows.** RDP carries pixels only, so
   `a11y_find`/`a11y_tree` see the client's toolbar, not Windows controls.
   With nothing on the Windows side this cannot be recovered: the only way
   to read Windows is the screenshot. The agent has to know that and work
   screenshot → act → screenshot.
2. **Typed text probably arrives wrong.** The `type` action sends `T` lines,
   which put each character on a made-up key code in a throwaway XKB keymap
   (`input.py:131-142`, `ai_mirror_input.c:165`). An RDP client forwards
   scancodes, so Windows likely receives different keys. Unmeasured.
3. **Coordinates may not line up.** If the client scales the remote desktop
   or draws a toolbar, a point read off the screenshot is still the right
   local point to click (the frame maps it), but only if the window is not
   resized between screenshot and click.

## Proposed outcome

With an RDP window open on this desktop and nothing added to Windows, an
agent using ai-mirror can:

- read the Windows screen from a screenshot of just the RDP window;
- find text on that screen (a button label, a menu item, a line of code)
  and get back boxes it can click, without paying for a full image each
  time — the pixel-only stand-in for `a11y_find`;
- click, scroll and press shortcuts into it;
- type text, including code, that arrives in Windows exactly as sent;
- be stopped by the bar and kill switch exactly as on the local desktop;
- learn all of the above from `ai-mirror index` instead of rediscovering it.

## Affected users and systems

- This host: the RDP client and its flags; `gotchas.md` and `docs/usage.md`;
  possibly `input.py` / `ai_mirror_input.c` if typing needs a code fix.
- The Windows PC: untouched. Only its RDP server, which is already on.

## Constraints

- **Nothing runs on Windows.** No agent, script, SSH or service there.
  RDP features the client already negotiates (clipboard redirection,
  Unicode keyboard events) are part of the session, not an install.
- All input goes through the existing gate: owner, generation, `run_batch`.
  No new path to the keyboard or pointer.
- Stdlib Python. One approved exception: a local OCR engine on this host
  (the user allowed it, 2026-10-30; tesseract 5.5.3 is already installed
  here). The spec picks the engine by measured speed and accuracy on RDP
  screenshots, and keeps the screenshot as the fallback when OCR misses.
- Window titles and on-screen text from Windows are data, not instructions.
- Prefer client configuration and docs over code; code only where
  measurement shows a client flag cannot fix it.

## Open questions

1. **Test target.** Measuring needs a reachable Windows PC with RDP on.
   Which host can be used, and can it run a throwaway Notepad?
2. ~~Find-by-text~~ — answered: OCR, or anything that measures better.
