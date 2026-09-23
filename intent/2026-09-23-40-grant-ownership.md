---
status: approved
issue: 40
author: olafkfreund
---

# Intent: a grant should belong to whoever was granted it

## Problem

An MCP server ending calls `control.set_owner('off', 'agent')` whenever the
owner is an agent (`mcp.py:256-264`). The comment says "an agent's grant, and
its unanswered request, end with its server", but nothing in the state says
whose grant it is, so the check cannot distinguish its own from anyone else's.
Any server exiting ends **any** agent's grant.

Measured twice on razer last night. This session drives razer through the CLI
over ssh and registers no server there; another agent's server was registered
as `/run/user/1000/ai-mirror/mcp.d/6176.json`. Both times control ended without
anyone asking:

    00:00:53  by agent, event off, was agent   -- mid-verification
    07:58:07  by agent, event off, was agent   -- mid-investigation

and by then `mcp.d/` was empty. The second cost a re-grant from the person at
the keyboard; the first cost one too, and twenty minutes of confusion about
what had revoked it.

The same gap has a second face: `control off` from any agent works on every
agent's grant. Two agents on one desktop is not hypothetical here -- it is how
last night went, and the bus traffic shows three sessions sharing these hosts
routinely.

From the holder's side this is indistinguishable from the human revoking
control, which is the one thing an agent is told never to retry through. So the
failure teaches the wrong lesson: it looks like the person took their desktop
back.

## Proposed outcome

- A grant records who holds it, using the identity servers already register:
  pid plus process start time.
- A server ending releases only a grant it holds. One taken by a CLI caller,
  which has no server, survives every server exit.
- An agent asking to release control releases only its own grant; the person at
  the keyboard keeps the unconditional stop -- the bar widget,
  `Super + Shift + Escape`, and a terminal -- with no ownership check in front
  of any of them.
- A refusal to release someone else's grant says so, rather than failing
  silently or pretending to succeed.

## Affected users and systems

`src/ai_mirror/control.py` (the state, `set_owner`, `_answer`,
`register_server`), `src/ai_mirror/mcp.py` (the shutdown block), and anyone
running more than one agent against one desktop -- which on these machines is
the normal case, not the exception.

## Constraints

- The person's stop must stay unconditional. No ownership check may ever stand
  between them and taking their desktop back.
- Must not strand the desktop: if the holder is gone, control must still become
  available without waiting for a human.
- No new files or daemons. The registration directory and the state file
  already exist.
- Older state without the new field must keep working: a grant made by a
  previous build has no holder recorded and must not become unreleasable.

## Open questions

1. When the holder's process is gone but its grant is still recorded -- a crash,
   or an abrupt termination -- who ends it? The ten-minute idle timeout
   eventually does. Should another server, or the next CLI call, release it as
   soon as it notices the pid is absent or its start time no longer matches?
2. Should an agent be able to release another agent's grant deliberately, given
   a flag or an explicit address? There is a case for it when a session hangs,
   and a case against it because the honest way is to ask the person.
3. Is the audit line enough? Today it records `by: agent` for every agent
   action; with holders recorded it could name which one, which is what would
   have made last night's two revocations obvious in seconds rather than an
   hour.
