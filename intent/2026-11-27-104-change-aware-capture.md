---
status: approved
issue: 104
author: olafkfreund
---

# Intent: Change-aware screenshots and short clips

## Problem

Successive screenshots give an agent no explicit signal about what changed. A transition that begins and ends between screenshots leaves no evidence in either frame.

## Proposed outcome

During an active control grant, an agent can compare two requested captures of the same target and see whether the pixels changed. When the frames cannot be compared, the agent gets an ordinary fresh frame and a reason. Use a real missed transition to decide whether a short clip is also needed.

## Affected users and systems

People granting desktop control and agents using ai-mirror screenshots to verify a desktop action.

## Constraints

- Scope the comparison to the control holder, generation and capture target. Recheck the grant before returning the result.
- Apply ai-mirror's privacy refusal to every frame. Bound image size, memory use and capture time. Keep the baseline in memory and discard it on revocation.
- Preserve ordinary screenshots and their existing input targeting rules.
- Treat mismatched target identity, geometry or scale as a fresh observation. A pair of frames can establish endpoint changes.

## Open questions

- Which missed transition should define success?
- Does that workflow need evidence from between observations, or are the changed pixels in the second frame enough?
