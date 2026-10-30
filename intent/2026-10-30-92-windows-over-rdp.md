---
status: draft
issue: 92
author: olafkfreund
---

# Intent: drive a Windows PC through an RDP window

## Problem

An RDP client (xfreerdp, Remmina) on this desktop is one more Hyprland window,
so ai-mirror can already screenshot it and click into it. Two things stop an
agent from actually working on the Windows machine behind it:

1. **It cannot read the Windows UI.** RDP carries pixels, not an accessibility
   tree. `a11y_find` and `a11y_tree` (`a11y.py`, AT-SPI) see only the client's
   own toolbar. Every step inside Windows costs a screenshot and a guess at
   pixel positions, which is slow and the main source of misclicks.
2. **Typed text probably arrives wrong.** The `text` action puts each character
   on a made-up key code in a throwaway XKB keymap (`ai_mirror_input.c:165`).
   Local Wayland clients read the keysym; an RDP client forwards the physical
   scancode, so Windows likely receives different keys. Not yet measured.

## Proposed outcome

With an RDP session open on this desktop, an agent using ai-mirror alone can:

- find Windows controls by name and role, with boxes it can click, the way
  `a11y_find` works for local apps;
- click, scroll and press keys into the session (works today);
- type text, including code, that arrives in Windows exactly as sent;
- be stopped by the bar and kill switch exactly as on the local desktop.

No separate MCP server and no second agent: the user adds nothing to Claude
Code beyond the ai-mirror server it already has.

## Affected users and systems

- This host: `a11y.py`, `api.py`, `mcp.py`, `input.py`, `control.py`
  (target checks), `index.py`/`gotchas.md`, `docs/usage.md`, tests.
- The Windows PC: needs a way to answer "what is on screen" (UI Automation,
  UIA). Something must run there; RDP alone cannot carry it.
- The RDP client in use, whose scaling and toolbar decide where a Windows
  pixel lands in the local window.

## Constraints

- **All actions go through the local gate.** Clicks and keys reach Windows
  only as ai-mirror input into the RDP window, after the owner and generation
  checks in `run_batch`. Whatever runs on Windows reads; it never clicks,
  invokes or types. Otherwise the bar and kill switch stop covering the work.
- Do not describe the gate as stronger than AGENTS.md allows: a channel that
  reaches Windows over SSH is the weaker case, as `ssh host ai-mirror mcp` is.
- Stdlib Python on this side, no new dependencies; the Windows side uses only
  what Windows ships (PowerShell, UIA, optional OpenSSH Server).
- Tests stay off the desktop and off the network: the new remote read is a
  `guard`-checked seam, stubbed in tests.
- Nothing read from Windows (control names, window titles) is treated as an
  instruction; it is data, like local a11y text.

## Open questions

1. **Transport to Windows.** OpenSSH Server (built into Windows, one optional
   feature) is the proposal. Acceptable to require it on the Windows PC?
2. **RDP client.** Which one do you use (xfreerdp, wlfreerdp, Remmina), and is
   smart-sizing or scaling on? It sets how coordinates are mapped.
3. **Scope of typing fix.** Fix `text` for RDP windows only (type with real
   key codes, or paste via clipboard redirection), or for every window?
