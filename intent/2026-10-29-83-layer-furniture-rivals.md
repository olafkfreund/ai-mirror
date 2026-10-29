---
status: draft
issue: 83
author: olafkfreund
---

# Intent: typing into a panel works when only the desktop's furniture shares its level

## Problem

With control granted on p620 (2026-10-29), ai-mirror refuses every keystroke
addressed to Nixi's overlay (`nixi`, layer level 3):

> another surface is open at the same level or above: omarchy-notifications …,
> accent-hold …; cannot tell which has the keyboard, so input was NOT sent.

`omarchy-notifications` (one per monitor) and `accent-hold` are mapped at level 3
all the time on this desktop. So typing into *any* overlay-level panel can never
succeed here: Nixi, the companion's card, menus that open at overlay level.

The two input guards disagree:

- typing at a **window** (`_refuse_new_surfaces`, #39) ignores surfaces mapped
  continuously since the grant, the desktop's furniture;
- typing at a **layer** (`_require_layer`, #29) treats every other surface at the
  same level or above as a rival, furniture included.

The supported way to type into a panel is the one that cannot pass. That pushes
callers outside ai-mirror. It happened: an agent fell back to `wtype`, Nixi had
closed by then, and the text landed in a terminal. That is the failure the guard
exists to stop.

## Proposed outcome

- An agent can type into a panel such as Nixi when the only other surfaces at its
  level or above are furniture: mapped continuously since the grant, as #39
  already defines it.
- A surface that opened after the grant, or left and came back, still blocks,
  exactly as today, with the same message.
- On p620: open Nixi, type a prompt through `input` addressed to its layer, and
  it arrives.

## Affected users and systems

- ai-mirror's input guard (`src/ai_mirror/control.py`); every host with an
  always-mapped overlay surface (p620 confirmed; razer likely, same shell).
- Blocks nixi-nixarchy#108's recording and nixi-nixarchy#114's live check.

## Constraints

- No widening beyond what the window path already accepts: the same baseline,
  the same #39 "left and came back" rule, and no namespace allowlist.
- A failed layer query must still fail closed for layer typing.
- Grants made before `baseline_layers` existed keep today's behaviour.

## Open questions

- Furniture at level 3 can still hold the keyboard. A notification with an inline
  reply is the obvious case, and the window path accepts that same risk today.
  Is that acceptable for layers too, or should furniture above the target's level
  (not equal to it) keep blocking? The spec will propose an answer.
