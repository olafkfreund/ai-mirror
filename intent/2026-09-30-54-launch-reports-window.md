---
status: draft
issue: 54
author: olafkfreund
---

# Intent: launch says which window it opened

## Problem

`launch` returns the pid of the process it started, and nothing else. What an
agent does next is almost always about the window: focus it, type into it,
move it. So it calls `windows` and guesses which row is new. The pid does not
help. Launchers (`uwsm-app`, `omarchy-launch-*`, `gtk-launch`) exit after
handing off, and single-instance apps such as browsers and editors open their
window from a process that was already running. Measured on this host: three
windows share one pid, so a pid does not name a window even when it matches.

A guessed window is the wrong target for everything that follows. #24 made
typing name its window precisely so that input cannot land somewhere
unintended. That protection is only as good as the address the agent picked.

There is a second problem. What `launch` starts lives in the MCP server's
systemd scope, and the MCP server lives in its terminal's scope (measured:
one server in a tmux scope, one in a foot scope). Close that terminal and
everything the agent launched goes with it. Omarchy's own launchers avoid
this by going through `uwsm-app`, which gives each app its own scope.
Nothing tells an agent to do the same.

## Proposed outcome

- `launch` reports the window it opened: its address when exactly one new
  window appeared, the candidates when several did, and neither when none
  appeared in time. Launching a program that opens no window is not an error.
- An agent reading `index` learns to launch desktop apps through `uwsm-app`,
  so they outlive the terminal that started the agent.

## Affected users and systems

- Agents using the `launch` MCP tool or `ai-mirror launch`: extra fields in
  the result, and the call now takes up to a few seconds instead of returning
  at once.
- `src/ai_mirror/api.py`, `mcp.py` (schema), `cli.py`, `gotchas.md`, tests,
  `docs/usage.md`.
- No change to the ownership gate, the helper or the plugin.

## Constraints

- `launch` stays argv-only, with no shell, `DEVNULL` for all stdio, and its
  own session. Nothing inherits the MCP stdout.
- It stays behind the owner + generation gate.
- Tests never start a process. Today nothing enforces that: `launch`'s
  `Popen` is the one seam that changes the world with no `guard.check`
  (the others are `host.ctl dispatch`, `Helper.start/.cmd` and the
  `a11y._busctl` write). It is safe only because no unit test calls `launch`.
  This change adds tests that do, so it adds the guard on that `Popen` first.
- ai-mirror does not rewrite the agent's argv (no silent `uwsm-app` prefix).
  Which program runs is the agent's choice, and the gotcha says why to choose
  `uwsm-app`.
- No new dependencies. The waiting should reuse `wait.poll` from #53, so this
  lands after #53.

## Open questions

1. How long to wait for a window? Apps vary widely: a terminal takes about
   0.2 s, a cold browser several seconds. Proposed: 5 s by default,
   overridable with `timeout` (≤30) as in `wait`, and returning early the
   moment one new window appears.
2. Should a window that appeared but belongs to no launched pid still count?
   Proposed: yes. Any window that is new since the launch counts, because
   pid attribution fails for exactly the single-instance apps that matter.
   Report it as `window` only when it is the only new one.
