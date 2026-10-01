---
status: approved
issue: 48
author: olafkfreund
---

# Intent: A stray keystroke cannot grant control

## Problem

`plugin/AgentConfirmDialog.qml` is the human's half of the control gate. It
opens when an agent asks, which is on the agent's schedule, not the human's,
and it takes exclusive keyboard focus. From that moment, `A` grants control.

A human who is typing when the request lands does not see the dialog before
their next keystroke. Any word with an "a" in it hands the agent the keyboard
and mouse. Enter and Return were already made to deny for this reason; letters
were not. The gate is "a request a human answers", and an accidental key is not
an answer.

The same holds for the mouse. The dialog opens over everything, under a
pointer that may already be on its way to a click, and a click on Allow
grants. The target is small, so this is less likely than a key, but it is the
same failure: input aimed at something else counts as consent.

## Proposed outcome

No key pressed before the human has noticed the dialog can grant control.
Allow still works from the keyboard (and by click) once the human deliberately
engages with the dialog. Deny keeps working immediately: Escape, Enter, `D`,
and the 30-second timeout all still deny.

## Affected users and systems

- The Omarchy bar plugin (`plugin/AgentConfirmDialog.qml`) on every host that
  uses it.
- Anyone answering a control request, by keyboard or by click.
- The MCP and CLI side is unchanged: `confirm_request` still grants, only the
  dialog's key handling changes.

## Constraints

- Deny must never become harder: no delay or arming step on any deny path.
- Must not add a way for the agent to arm or answer the dialog.
- The plugin directory stays free of symlinks (Nixarchy validator).
- Must not claim more than it is: this closes accidental grants by the human.
  It is not a defence against an agent with a shell (AGENTS.md invariant).

## Open questions

1. Which arming rule for the keyboard?
   - (a) `A` is inert until the human presses an arrow key or Tab, as
     omarchy-omcp does. *Weakness:* arrows are part of ordinary editing
     (move the cursor, then type), so "arrow, then a" happens mid-sentence.
   - (b) `A` is ignored for a short time after the dialog opens. It guesses
     how fast people notice things.
   - (c) Both (a) and (b).
   - (d) **The first key decides.** While unarmed, an arrow key or Tab arms
     Allow, and *every other key denies*. Once armed, `A` grants. A human who
     is typing when the dialog lands denies it with their next keystroke,
     which is the safe outcome; the agent sees `owner: off` and may ask
     again. Granting by accident needs the first stray key to be an arrow and
     the next to be `a`.

   Proposed: (d). It fails closed instead of guessing at timing, and it
   turns accidental typing into a denial rather than leaving the dialog open
   for the next key. **Decided: as proposed.**
2. Should a click on Allow also need the dialog to be armed (by an arrow key,
   Tab, or first moving the pointer onto the dialog)? Proposed: yes. A click
   arms only once the pointer has moved after the dialog appeared, so a click
   already on its way cannot land. **Decided: as proposed.**
3. Should the dialog show that Allow is not armed yet, e.g. "press → then A"?
   Proposed: yes, otherwise the human does not know why `A` does nothing. **Decided: as proposed.**
