---
status: approved
issue: 10
intent: intent/2026-09-19-10-control-needs-a-human.md
---

# Spec: an agent cannot take control of the desktop without a human confirming it

## The threat model, said plainly first

Everything ai-mirror runs, and every agent it serves, runs as **the same user**.
An agent that has a **shell** can do anything that user can do:

- write `$XDG_RUNTIME_DIR/ai-mirror/state.json` directly (it is ours, `0600`);
- run any command, `ai-mirror` included;
- synthesize keys and clicks through the Wayland virtual-keyboard and
  virtual-pointer protocols, the same ones `ai-mirror-input` uses. That is
  enough to press a button in any prompt we show.

**No user-space confirmation channel is unforgeable against a same-uid agent
with a shell.** Kernel `ptrace_scope` is 1 on nixarchy, which stops it reading
another process's memory. It does not stop it writing our files or driving our
seat. A channel that would hold (a different uid, or a compositor that tells
physical from virtual input and refuses the latter for this one prompt) is out
of reach here. We know of no Hyprland setting that makes a bind or a layer
surface refuse virtual input, and ai-mirror does not run privileged code. The
implementer checks the first part before building; if such a setting exists,
it strengthens this design and does not change it.

So the gate protects against three things, and the spec does not claim more:

1. **Agents that only reach ai-mirror through MCP.** These have no shell: an
   MCP-only client, or a tool-restricted one. For them the gate is
   **unforgeable**. The confirm operation is not an MCP tool, and nothing
   reachable through MCP writes the grant.
2. **Prompt-driven self-grants.** An agent told "call control with mode=agent
   first", as nixarchy-voice's prompt does today, now gets a refusal, not a
   grant, unless a human says yes.
3. **Quiet circumvention.** An agent with a shell *can* forge a yes. Doing so
   takes a deliberate act (running `ai-mirror control confirm`, writing the
   state file, or clicking the prompt with a virtual pointer), and that act is
   visible. The prompt is on screen, the mark goes red, and the audit log gets a
   line for every request and answer. It turns a silent capability into a
   visible, logged break-in.

For shell-capable agents, the real protection is **not handing them ai-mirror
at all** unless the person opted in. That is nixarchy-voice#17's
`desktopControl` flag and nixarchy#773's rule of no automatic MCP registration.
This spec does the part ai-mirror can do.

## Design

### Control has a pending state

`control.set_owner(mode='agent', ...)` no longer grants. From any caller (MCP,
CLI or API, since all go through `api.run`), it writes:

```json
{"owner": "pending", "generation": N+1, "request": {"id": "<16 random hex>",
 "by": "agent|human", "since": "...", "expires": "<now+30s>"}}
```

It then returns `{"owner": "pending", "request": id}` to the caller, which must
poll `status` until the owner is `agent` or `off`. The MCP `control` tool's
description and the server's `INSTRUCTIONS` say so. "The human is asked; wait
for status" replaces "call control with mode=agent before acting".

Because `require_agent` only accepts `owner == "agent"`, nothing acts while a
request is pending. That existing check is the whole enforcement point; no new
checks are needed at the action sites.

### The prompt: ai-mirror's own bar widget

`plugin/Widget.qml` already watches `state.json`. On `owner == "pending"` it
opens a small layer-shell dialog on the focused output. It has keyboard focus,
shows who asked (`by`) and a countdown, and offers **Allow** / **Deny**, with
Deny as the default and Escape meaning deny. The answer runs:

```
ai-mirror control confirm <id>     # Allow
ai-mirror control deny <id>        # Deny
```

through the widget's existing `Command.qml`.

The widget is used rather than a notification because:
- it is ai-mirror's own, so there is no dependency on the notification daemon's
  action support;
- it **fails closed**. If the widget isn't enabled, nobody sees a prompt, the
  request expires, and control stays off. The refusal says "no confirmation
  surface: enable the ai-mirror bar widget".

### `confirm` and `deny`

- **CLI-only:** new subcommands of `control`. They are **not MCP tools** (the
  tool list is unchanged; the `control` tool keeps only `mode`), and `api.run`
  refuses them when `by == 'agent'`.
- `confirm <id>` succeeds only if a request with that id is pending and
  unexpired. It then sets `owner: agent`, `enabled_by: human-confirmed`,
  `request_by: <original by>`, bumps the generation, and records
  `last_input: now`. A wrong, expired or already-answered id gets `bad_request`.
- `deny <id>`, or expiry, sets `owner: off` and bumps the generation.

### What doesn't prompt

- `control off`, the kill switch (Super+Shift+Escape) and a closing MCP server
  (`mcp.py:251`) **never** prompt. They set `off` directly, as today, and clear
  any pending request.
- **Running it yourself goes through the same prompt.** A person typing
  `ai-mirror control agent` in a terminal answers the dialog too, because an
  agent with a shell can run that same command. The prompt is the only
  difference between them (intent constraint).

### Timeout and expiry (the intent's open question, decided)

- **A request expires after 30 seconds** unanswered, and the owner goes back to
  `off`. It is checked on every `status` and `read_state` call against
  `expires`, and the widget's countdown shows it. No daemon or timer process is
  needed.
- **A grant ends at whichever comes first:**
  1. the requesting MCP server exits (existing, `mcp.py:251`);
  2. **10 minutes without an `input`, `window`, `launch` or `a11y_act`**.
     `require_agent` compares `now` with `last_input` and sets `off` once it
     has passed. `run_batch` and the other mutating operations refresh
     `last_input`;
  3. the person revokes it.

  So an agent that stops working loses the desktop by itself. An agent actively
  working keeps it for as long as it acts.

### Watching is visible

Observing operations stay ungated, as the owner decided. Those are
`screenshot`, a `clipboard` read, `a11y_tree`, `a11y_find`, `index` and `wait`.
When `by == 'agent'`, `api.run` touches `$XDG_RUNTIME_DIR/ai-mirror/watching`
(an mtime, with no content) before running them. The widget shows a distinct,
steady **watching** mark while that mtime is under 5 seconds old. It reuses the
same drawn mark in a neutral colour, never red, and doesn't pulse. Red and
pulsing stay reserved for control. Its tooltip says "an agent is reading the
screen".

### Audit log

Every request, confirm, deny, expiry and revoke appends one JSON line to
`$XDG_RUNTIME_DIR/ai-mirror/audit.jsonl`: time, event, id, `by`, generation.
It is the record that makes a forged confirm visible after the fact. It's
runtime-dir only, so it's gone at logout, and nothing is written to disk
permanently.

### `LICENSE` and `NOTICE` in every output

`ai-mirror`, `ai-mirror-input` and `plugin` each install `LICENSE` and `NOTICE`:
into `$out/share/doc/<pname>/` for the two programs, and at the root of the
plugin directory, where `omarchy-plugin-validate` accepts plain files. A flake
check asserts all three outputs contain both files.

## Alternatives rejected

- **A notification with Allow and Deny actions.** The Omarchy notification
  service supports actions, but it is not ai-mirror's to rely on, and it can be
  dismissed without an answer. It is no harder to forge than the widget: an
  agent can click it with a virtual pointer too.
- **A per-read grant for observation.** The owner decided on a visible
  indicator (intent, "Decided on approval").
- **Signing the grant with a secret the agent can't read.** Any secret the
  verifier can read, a same-uid agent can read too. Holding it only in the
  widget's memory fails, because the verifier is a different process. It adds
  code and protects nothing.
- **A privileged confirm helper, a different uid or a setuid helper.** That
  would be real protection, but it is a system-level component in a user-level
  tool, and a new attack surface. Out of scope; if it's ever wanted, it's a
  separate issue.
- **An absolute grant lifetime.** It would cut off an agent in the middle of
  long, legitimate work. Idle expiry ends only grants nobody is using.

## Risks

- **An agent that polls `status` in a tight loop** while waiting. The server's
  `INSTRUCTIONS` tell it to wait with backoff, and `status` is cheap (it reads
  one file).
- **No prompt while the widget is off:** control can't be granted at all. That
  is the intended fail-closed behaviour, and the refusal names the fix.
- **nixarchy-voice's backend,** which drives the desktop through MCP, now waits
  for a human. It must handle `owner: pending`. nixarchy-voice#17 gates it off
  by default anyway.
- **An existing user of `ai-mirror control agent` in scripts** now gets a
  prompt. It's a deliberate, documented behaviour change.

## Verification

Tests go in `tests/test_invariants.py`'s style: pure functions and the state
file, with no compositor. Each is shown failing on `295762d` (today's
`master`) first.

| Test | Red on today's code because |
|---|---|
| `set_owner('agent', 'agent')` leaves `owner: pending` and `require_agent` refuses | today it grants immediately |
| `set_owner('agent', 'human')` is pending too (the CLI path) | today it grants |
| `confirm` with a wrong id, an expired id, or a second time → `bad_request`; with the right id → `agent`, `enabled_by: human-confirmed` | there is no confirm |
| `api.run('control', {'mode': 'confirm'}, by='agent')` is refused, and the MCP tool list has no confirm | an MCP agent could otherwise answer itself |
| a request left 31 s (clock injected) reads back as `off` | there is no expiry |
| `require_agent` after 10 min idle (clock injected) → `off`, `not_owner` | there is no idle expiry |
| `control off` while pending clears the request, with no prompt | there is no pending state |
| an observing op with `by='agent'` touches `watching`; with `by='human'` it doesn't | there is no watching file |
| every event appends one line to `audit.jsonl` | there is no log |
| flake check: `LICENSE` and `NOTICE` in `ai-mirror`, `ai-mirror-input` and `plugin` | none ship them |

The widget's dialog is checked by hand on a live session: Allow grants, Deny and
Escape refuse, the countdown expires, the watching mark appears and fades.
There's no display in the test suite, as with the existing mark.

**Decided on approval (owner, 2026-09-19):** the stated limit is accepted: the gate holds for agents reaching ai-mirror through MCP alone, and an agent with a shell as the same user could answer its own prompt.
