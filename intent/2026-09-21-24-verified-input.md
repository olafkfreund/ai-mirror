---
status: approved
issue: 24
author: olafkfreund
---

# Intent: A keystroke should not land in a window nobody chose

## Problem

`input` types into whatever holds focus at the instant the keystroke arrives.
Nothing records which window was intended, so nothing can notice when it is no
longer the one in front.

Two mechanisms look like they cover this and neither does:

- **`generation`** (`control.py:233`, `require_agent`) answers *"do I still have
  permission"* — it fails closed when the human revokes control mid-batch. It
  says nothing about which window is focused.
- **`frame`** (`mcp.py:125`, `from_frame`) answers *"are these coordinates from a
  current view"*, mapping frame-relative pixels to global ones. It only applies
  to actions that carry coordinates. A `type` or `key` action
  (`input.py:107,119`) has none, so a frame cannot bind it to anything.

Between them there is no answer to *"is the window I meant still in front"*, and
that is the question a keystroke depends on.

## This has already gone wrong, on a real desktop

From the agent bus, one session to another:

> "In the last minute the shell was restarted (not by me) and a MicroVMs popup
> opened where mine was. Its 'Delete t1 and everything in
> ~/.local/state/nixarchy/microvm/t1?' dialog is up, with Cancel focused. My key
> guard only checks for the generic `omarchy-keyboard-panel` layer, so one `y`
> keystroke of mine may have landed in your panel after the restart."
>
> "**A layer-namespace guard is not ownership.**"

A delete-confirmation dialog and a stray `y`. The agent in question had built a
guard and it was the wrong kind — it checked what *sort* of thing was in front,
not whether it was *the* thing.

## Proposed outcome

An agent cannot send a keystroke to a window it did not deliberately target and
that is not still focused. When focus has moved, input fails closed with a
refusal that says how to recover, rather than landing somewhere unintended.

A second, smaller outcome: the success message stops overstating. Today a
delivered keystroke reads as success; it should say the keystroke was delivered
to a named window and that nothing about the application accepting it, or the
task completing, has been established.

## Prior art

[omribenami/Omarchy-AI](https://github.com/omribenami/Omarchy-AI) (MIT),
`src/omarchy_ai/execution/verified_input.py`, 108 lines. Its `InputGuard`
establishes focus through an explicit call, **verifies it by re-reading the
focused address** rather than trusting the call's return, re-checks the pin
before every keystroke, and clears it on anything that moves focus.

It also walks the terminal's process tree for a foreground editor and refuses
conversational text there — on the reasoning that a stray keystroke at a shell
prompt fails harmlessly with "command not found", while in a modal editor it is
**interpreted as editing commands** and silently corrupts the buffer. Same
keystroke, different blast radius, and the process tree is what tells them apart.

We should take the idea, not the file: their model is a long-lived conversation
object, ours is a granted generation with a lock, and the lifetime question
below is a real difference rather than a detail.

## Affected users and systems

`input` (keyboard actions), `mcp.py`'s tool surface, and whatever records the
pin. Pointer actions are already frame-bound and may need nothing.

## Constraints

- **Must fail closed.** An unverifiable focus blocks input; it does not warn and
  proceed.
- Must not weaken `generation` or the ownership checks — this is an additional
  question, not a replacement for either.
- Must not require an extra round trip for the common case of "focus something,
  then type into it".
- The refusal has to tell the model how to recover, or it will simply retry.

## Open questions

1. **What is the pin's lifetime?** We already have `generation` and a control
   lock. Reusing the generation is tempting and probably wrong: control can be
   held across many focus changes, so a pin that lives as long as the grant
   would authorise typing into a window focused ten actions ago. Per-batch,
   per-explicit-focus, or a new object?
2. **Do pointer actions need anything?** `frame` already ties coordinates to an
   observation. If a frame is current, a click is arguably already verified, and
   adding a focus check to clicks may refuse legitimate ones — clicking a window
   that is *not* focused in order to focus it is normal.
3. **Does the editor heuristic belong here or beside the sensitive-window
   patterns (#19)?** Both are "refuse based on what is in front of you". The
   privacy layer already has that shape, and two refusal systems would be one
   too many.
4. **Is refusing "please…"-shaped text into a terminal ours to make?** It caught
   a real LLM failure for them, but it is a heuristic on content rather than on
   state, and a wrong refusal is invisible to the user. It may belong in a later
   issue on its own evidence.
