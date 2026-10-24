---
status: approved
issue: 72
author: olafkfreund
---

# Intent: release the background accessibility work and show it

## Problem

Master has moved well past 2.1.0, but nothing a user reads says so:

- #65: `a11y_act` is guarded, clicks only clicks, reads its result back and
  reports `not_confirmed` honestly, and every mutating call now needs
  `generation`. That last one breaks existing callers.
- #66: `index` no longer blanks when a special workspace has no id.
- #68: a key-up after its target closes no longer fails the batch.
- #70: `set_value` and `select` move sliders and pick list items through
  AT-SPI, and tree rows carry `value`.

The README's feature table still says `a11y_act` "clicks, focuses or fills".
The screencast (`assets/demo-desktop.mp4`) shows the pointer doing the work,
so the new story isn't shown anywhere: the agent works in a window you're not
looking at while your own cursor and keyboard stay yours. There is also no
tag that nixarchy can pin.

## Proposed outcome

- A release with notes that lead with the breaking change (`generation` is
  required) and say how to adapt.
- README and `docs/usage.md` describe what an agent can do without the
  pointer, which apps support it (the measured table), and where it stops
  (page-owned ARIA state, GTK4 text it cannot read back).
- A short showcase recording. The human keeps typing in a terminal while
  the agent, on another workspace, sets a slider, picks a list item and
  fills a form in a browser, each step confirmed by read-back. The README
  embeds it.

## Affected users and systems

Anyone calling ai-mirror's MCP or CLI, because the `generation` change
breaks old calls. Readers of the README and the GitHub page. nixarchy, which
pins ai-mirror (nixarchy#1436 follows this release).

## Constraints

- Recording drives the real desktop, so it runs only under a grant from the
  confirm dialog, with notifications silenced, a scratch Chrome profile, and
  an empty workspace (AGENTS.md "Before recording anything").
- Claims match measurements. Nothing says "works in every app".
- The index payload stays under its 22,000-byte cap.

## Open questions

1. Version: is it **3.0.0**, because the required `generation` breaks
   callers, or **2.2.0** with the break called out? I propose 3.0.0.
2. Showcase form: a recording of about 40 s with no voice, kept under the
   10 MB GitHub embed limit, plus a GIF for the README? I propose both: the
   mp4 as the asset and a GIF cut from it.

**Decided: as proposed** (3.0.0; mp4 plus a GIF cut from it).
