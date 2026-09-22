---
status: approved
issue: 30
author: olafkfreund
---

# Intent: what ai-mirror says it did, and what it did

## Problem

A full keyboard and mouse sweep on razer (Hyprland 0.56.0, single 1920x1080
output, AT-SPI on) drove a text editor, a calculator and Chrome through every
input, window, clipboard, capture and accessibility call the tool exposes.
The input path itself is sound: typing is byte-exact including Unicode and
astral-plane emoji, chords, held modifiers, explicit key_down/key_up,
single/double/triple click, drag, scroll, every window operation and the
clipboard round-trip were each verified by reading the result back, not by
trusting the tool's own `ok`.

What is wrong is not what ai-mirror does. It is what ai-mirror **says** it did.
Nine findings, and they are one family: every result that a caller cannot
independently check is capable of being wrong in the direction that makes an
agent proceed confidently.

1. **A refused batch has already delivered part of its input** (#30). The
   focus recheck runs before every encoded line; a failure on a later line
   raises "input was NOT sent" over lines that were already sent. Measured:
   an error returned while `SECRET-ABC-123`, a Return and a Ctrl+D all landed
   in the window, which the capture guard had simultaneously refused to
   photograph as a password manager.
2. **Input aimed at a window lands in a layer surface, reported as success**
   (#29). With an overlay open, `type --window <editor>` answered "delivered
   to 0x...ea10, which still had focus"; the text appeared in the overlay's
   prompt and the editor buffer was verified untouched.
3. **The supported way to type into a layer surface cannot succeed** (#29).
   Refused for nixi and for vimarchy: Hyprland never reports the surface as
   focused, so the documented workflow is unreachable while the undocumented
   one works by accident.
4. **A focus mismatch is reported with the code for a revoked grant** (#31).
   `stale_generation` is documented as "the human revoked control"; an agent
   that believes the code stops instead of focusing the window it meant.
5. **`doctor` passes while the compositor is unreachable** (#32). The one
   condition that breaks every other subcommand is the one the self-check
   does not look at.
6. **The a11y tree is hollow for GTK4 yet reports `content: true`** (#33),
   and the walker's depth numbering shows it is dropping nodes.
7. **A control request from the CLI is attributed to "human"** (#34). That
   field is what tells the person at the keyboard who wants their desktop.
8. **`a11y set_text` refuses Chromium inputs that report `editable`** (#36),
   with one message covering two different causes and no mention of the
   focus-then-type path that does work.
9. **The middle mouse button is acked and does nothing** (#37), in Chrome and
   in GTK, while left, right, back and forward all work.

Plus one presentation nit: `screenshot --region` rejects the JSON form the MCP
tool hands an agent, without naming the form it wants (#35).

The thread: a caller driving someone's real desktop has no way to see what
happened except what these calls tell it. A refusal that already typed, a
success that names the wrong surface, and a health check that passes while
nothing works are each worse than an outright failure, because each one ends
the agent's investigation.

## Proposed outcome

- No call reports that input was not sent when part of it was. Either nothing
  is delivered before the decision, or the result states how much was.
- A result that names a destination is right about the destination, or says
  it could not tell.
- Error codes distinguish "you lost control" from "that is not the focused
  window"; a caller can act on the code alone.
- `doctor` fails when the compositor cannot be reached, and names why.
- `content: true` means there is content to act on.
- A request for control is attributed to whoever made it, over either transport.
- Where a capability does not work (middle button, Chromium `set_text`), the
  caller is told, in the result or in the gotchas, rather than getting `ok`.

## Affected users and systems

`src/ai_mirror/control.py` (the input batch and both focus guards),
`host.py` (what "focused" means when a layer holds the keyboard), `a11y.py`,
`index.py` and `gotchas.md`, `cli.py`, and the MCP surface in `mcp.py`.
Anyone driving a desktop through ai-mirror — the razer and p620 hosts here,
and any agent that reads a refusal and believes it.

## Constraints

- Must not weaken the guards to fix the reporting. #24's guarantee and the
  privacy refusals stay; this is about truthfulness, not permissiveness.
- Must not make a partial delivery silently acceptable — the point is that the
  caller learns of it.
- The middle-button loss looks to be downstream of ai-mirror (the helper sends
  every button identically); if it cannot be fixed here, it must be documented
  rather than left to report `ok`.
- Fixes land in one branch but stay separable per issue, so a risky one can be
  dropped without losing the rest.

## Open questions

1. For #30, which is wanted: refuse before delivering anything (check once,
   send atomically), or report the prefix that landed? The first is safer; the
   second is honest about a desktop that can move mid-batch. A batch of 16
   actions cannot be made atomic against a human at the keyboard, so a
   combination may be needed.
2. For #29, is there a way to learn which surface holds the keyboard on
   Hyprland 0.56 short of a protocol change? If not, should the window-
   addressed path refuse whenever any keyboard-capable layer is mapped?
3. Is the middle button worth chasing into the compositor, or documented as
   unavailable for now?
