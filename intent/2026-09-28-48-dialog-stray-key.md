---
status: draft
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

## Proposed outcome

No key pressed before the human has noticed the dialog can grant control.
Allow still works from the keyboard (and by click) once the human deliberately
engages with the dialog. Deny keeps working immediately: Escape, Enter, `D`,
and the 30-second timeout all still deny.

## Affected users and systems

- The Omarchy bar plugin (`plugin/AgentConfirmDialog.qml`) on every host that
  uses it.
- Anyone answering a control request by keyboard; mouse users are unaffected.
- The MCP and CLI side is unchanged: `confirm_request` still grants, only the
  dialog's key handling changes.

## Constraints

- Deny must never become harder: no delay or arming step on any deny path.
- Must not add a way for the agent to arm or answer the dialog.
- The plugin directory stays free of symlinks (Nixarchy validator).
- Must not claim more than it is: this closes accidental grants by the human.
  It is not a defence against an agent with a shell (AGENTS.md invariant).

## Open questions

1. Which arming rule? (a) `A` is inert until the human presses an arrow key or
   Tab (what omarchy-omcp does); (b) `A` is ignored for a short time after the
   dialog opens; or (c) both. Proposed: (a), because a time window guesses at
   how fast people type and (a) depends only on a deliberate act.
2. Should the dialog show that Allow is not armed yet, e.g. "press → then A"?
   Proposed: yes, otherwise the human does not know why `A` does nothing.
