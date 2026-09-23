---
status: draft
issue: 40
intent: intent/2026-09-23-40-grant-ownership.md
---

# Spec: a grant should belong to whoever was granted it

## Design

The identity already exists. `register_server` writes `{pid, start}` per
server, and `proc_start` reads a process's birth time precisely so a record
survives pid reuse. A grant records the same pair, and every release by an
agent is checked against it.

### Recording the holder

`register_server` sets a module-level `SERVER = {'pid': …, 'start': …}` as well
as writing the file. `set_owner('agent', …)` copies it into the pending
request as `request['server']`, and `_answer` carries that onto the granted
state as `held_by`. A CLI caller has no server, so `SERVER` is `None` and
`held_by` is written as `null`.

Three states, and they mean different things:

| `held_by` | means | an agent may release it |
| --- | --- | --- |
| `{pid, start}` | a server holds it | only that server, or once it is gone |
| `null` | a CLI caller holds it; no server can speak for it | no |
| absent | granted by a build before this change | yes, as today |

The absent case is what keeps a live grant from becoming unreleasable across
an upgrade. It disappears on its own the first time control is re-taken.

### Checking a release

`set_owner('off', by)` gains one rule, and only for `by == 'agent'`:

- `held_by` absent -> allowed, exactly as today;
- `held_by` matches `SERVER` -> allowed;
- the holder is no longer running -> allowed (below);
- otherwise -> `MirrorError('not_owner', "control is held by another agent
  (server pid N); ask the person at the keyboard to stop it, or wait for it to
  end")`.

`by == 'human'` skips the rule entirely. The bar widget, `Super + Shift +
Escape` and a terminal all reach `set_owner('off', 'human')`, and none of them
may ever be refused — that is the one property this change must not touch.

**Answer to open question 1:** a holder that is not running does not hold
anything. `_holder_running(held_by)` compares `proc_start(pid)` with the
recorded `start`: absent process, or a different birth time, means gone, and
any agent may then release. Nothing waits for the idle timeout, so a crashed
session cannot strand the desktop.

### The server shutdown

`mcp.py`'s `finally` block stops calling `set_owner` directly and calls
`control.release_if_held(SERVER)`, which releases only when the state's
`held_by` matches, and is silent otherwise. The pending-request case is kept:
an unanswered request made by *this* server still lapses with it.

**Answer to open question 2:** no takeover flag. A hung session's grant ends by
the ten-minute idle timeout, by its process dying, or by the person stopping
it — three exits without adding a way for one agent to take a desktop from
another. If the need turns out to be real, it can be added knowing why.

**Answer to open question 3:** yes, the audit names the holder. `audit()` calls
around grants and releases gain `holder` (the pid, or `null`, or absent), which
is what would have identified last night's two revocations in seconds.

## Alternatives rejected

- **A token in the state that the holder must present.** Equivalent security
  from a caller's point of view, but a token has to be stored and passed by
  every caller, where a pid and a start time are already there and need no
  plumbing.
- **Refuse all agent releases; only the human may stop an agent.** Simple, and
  wrong: a well-behaved agent releasing control when it finishes is the
  behaviour to encourage, and this would punish it.
- **Let the last server standing clean up any agent grant.** That is today's
  behaviour with extra words; it cannot tell a finished grant from a live one.
- **Record the session or MCP client name instead of the pid.** Nothing hands
  the server a stable client identity, and inventing one means a handshake this
  does not need.

## Risks

- **A mixed fleet.** A host running an older server alongside a newer one
  behaves as today for grants that server makes: it will still release anyone's
  grant, because the check lives in the newer code. The fix is complete only
  once every server on a host is updated, which on these machines means one
  rebuild.
- **A CLI-held grant now outlives every server.** That is the point, but it
  means a grant taken over ssh ends only by the idle timeout, the person, or
  the same CLI. A session that forgets to release leaves the desktop marked for
  up to ten minutes.
- **pid reuse inside one start time.** `proc_start` exists for this and the
  comparison uses it; a reused pid with a different birth time reads as gone,
  which errs toward releasable rather than toward stuck.
- **razer, p620**: agents that currently release control on exit and happen to
  release someone else's will start getting `not_owner`. That is the bug being
  fixed, but it is a behaviour change for any script that relied on it.

## Verification

- Unit: a grant made with a `SERVER` records `held_by`; one made without
  records `null`; `_answer` carries it from the request.
- Unit: `set_owner('off', 'agent')` is refused when `held_by` names another
  live process, allowed when it matches, allowed when `held_by` is absent, and
  allowed when the recorded process is gone or its start time differs.
- Unit: `set_owner('off', 'human')` is allowed in every one of those cases.
- Unit: `release_if_held` releases a matching grant, leaves a non-matching one,
  and still lapses this server's own unanswered request.
- Unit: the audit line for a grant and a release carries `holder`.
- Live on razer: take control through the CLI, start and stop an MCP server on
  the host, and confirm the grant survives — the exact sequence that ended it
  twice last night.
