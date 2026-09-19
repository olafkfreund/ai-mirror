---
status: draft
issue: 10
author: olafkfreund
---

# Intent: an agent cannot take control of the desktop without a human confirming it

## Problem

ai-mirror's whole promise is that a person can hand an agent the desktop and
take it back with one key. Today the "hand" half doesn't involve the person at
all. `control.set_owner` (`src/ai_mirror/control.py:86-97`) accepts
`mode=agent` from any caller. Its `by` argument records who asked, but nothing
checks whether a human agreed. `api.run`'s `control` op (`src/ai_mirror/api.py:38`)
is the same code behind the MCP tool, the CLI (`cli.py:23`) and the API. So any
agent that can reach ai-mirror can grant itself the mouse and keyboard. This
isn't hypothetical: nixarchy-voice's Claude backend registers ai-mirror when it
finds it on `PATH`, and prompts the agent to call `control mode=agent` first.

Watching needs no grant at all. `screenshot`, a `clipboard` read,
`a11y_tree`/`a11y_find` and `index` (`api.py:40-66`) work with control off.
The red bar mark (`plugin/Widget.qml:20`) only lights for `owner == agent`,
so an agent can read the screen and the clipboard with nothing on screen to
say so.

The package outputs (`flake.nix:13-51`) ship neither `LICENSE` nor `NOTICE`.
The MIT licence names two copyright holders and requires the notice to go
with the software.

nixarchy wants to install ai-mirror by default (olafkfreund/nixarchy#773), and
it can't while any of these hold.

## Proposed outcome

- `control mode=agent` takes effect only after a person says yes, through a
  prompt they can't miss (a notification with Allow/Deny, or a small dialog),
  on every entry point: MCP, CLI and API. With no answer within a timeout, or a
  Deny, control stays off and the caller gets a clear refusal.
- Handing control *back* (`mode=off`, or the kill switch) never needs
  confirmation.
- While an agent is observing (screenshot, clipboard read, a11y reads, index),
  something visible says so. The proposal is the bar mark in a distinct
  "watching" state, rather than a grant per read.
- Every package output carries `LICENSE` and `NOTICE`.

## Affected users and systems

Everyone who runs ai-mirror with any MCP client, including nixarchy-voice's
backend. It affects the control, API and CLI code, the bar plugin's widget and
the flake's outputs. nixarchy's #773 depends on it.

## Constraints

- **The confirmation can't be answered by the agent it protects.** It needs a
  channel an agent driving the same session can't click through: a
  notification action it can't reach while control is off, since that is the
  state it's asking to leave. The spec has to show why the chosen channel holds.
- **The kill switch stays instant** and never prompts.
- **No confirmation loop for the human's own use:** running
  `ai-mirror control agent` yourself in a terminal still goes through the same
  prompt, because an agent with a shell can run that command too. The prompt
  is the only thing that tells the two apart.
- The existing tests (`tests/test_invariants.py`) keep passing, and the new
  behaviour gets its own regression tests, each shown failing first.

## Open questions

1. **Observation:** a visible "watching" indicator (proposed), or a separate
   grant for reads? A grant is stricter, but it prompts on every screenshot an
   agent takes while helping.
2. **The timeout**, and whether a confirmed grant expires on its own (for
   example after N minutes, or when the MCP session ends; the latter already
   happens, `mcp.py:251`).
