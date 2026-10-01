---
status: approved
issue: 57
author: olafkfreund
---

# Intent: The audit log says what answered a control request

## Problem

`audit` is the record a person reads to decide whether to trust an agent
(#44): who asked for the desktop, and who let them have it. It records the
first half and not the second.

- A `confirmed` or `denied` event logs the request id and `by`, and `by` is
  the **asker** (`control._answer`).
- Nothing records what answered. Every answering path produces the same
  line:
  - a key in the dialog;
  - a click on Allow;
  - the dialog timing out;
  - `ai-mirror control confirm` typed in a terminal;
  - the same command run by some other process on the account.
- `control confirm` with no id confirms whatever request is pending
  (`api.py:192-197`). So a process does not even need to know which request
  it is approving.

On 2026-10-01, during #48's live check on p620, two requests were confirmed
while the human at the keyboard pressed and clicked nothing: `ed9dd7b7…` at
15:45:24 and `bfd8f719…` at 15:45:46. The log cannot say whether the dialog
did it, and from which input, or whether a process ran the CLI. The cause is
still unknown, and with today's log a repeat would be just as untraceable.

## Proposed outcome

Every `confirmed` and `denied` entry in `ai-mirror audit` says how the
answer arrived, and from which process:
- the path: a dialog key (and which key), a dialog click, a dialog timeout,
  or the CLI;
- the answering process and its parent: pid, and the parent's command name;
- whether the request id was given explicitly or picked up as "whatever is
  pending".

Reading the log after an event like 15:45 shows which of these it was.

## Affected users and systems

- The person reading `ai-mirror audit`: more fields, and the human-readable
  rendering shows them.
- `plugin/AgentConfirmDialog.qml` and `AgentCommand.qml`: the dialog says
  which input answered when it runs the CLI.
- `src/ai_mirror/control.py` (`_answer`, `audit`), `api.py`, `cli.py`.
- No change to the gate itself, MCP, the helper or input.

## Constraints

- **Evidence, not proof.** A process on the same account can lie about its
  path, and can set its own command name. The fields record what the
  answering process reported and what the OS showed. They must be described
  that way, never as attribution an attacker cannot forge. AGENTS.md already
  says the gate is weaker against a shell on the account, and this must not
  claim otherwise.
- **Additive only.** Existing audit lines and their readers
  (`render_audit`, `read_audit`, the tests from #44) keep working. Old
  entries simply lack the new fields.
- `audit` stays CLI-only (#44): no MCP exposure.
- No new dependencies. `/proc` is read with the stdlib.

## Open questions

1. **Should a bare `control confirm` (no id) still be accepted?** Requiring
   an id doesn't stop a determined process, since it can read the state
   first. It does stop a generic or accidental "confirm whatever is
   waiting", and it makes every confirm name what it approves. The cost: a
   human confirming from a terminal must copy the id (`status` shows it).
   Proposed: **require an id for `confirm`; keep `deny` id-optional,**
   because denying blindly is always safe. **Decided: as proposed.**
2. **The dialog may exist three times over.** Quickshell logs every open and
   close of the dialog's layer three times, which suggests one
   `AgentConfirmDialog` per bar instance, stacked. Proposed: **separate
   issue.** It belongs with #48's dialog, and #57 should not wait on it. But
   #57's `via` field will show it, if each instance also reports which bar
   it belongs to. **Decided: as proposed.**
