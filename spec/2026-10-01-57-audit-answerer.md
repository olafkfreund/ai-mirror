---
status: draft
issue: 57
intent: intent/2026-10-01-57-audit-answerer.md
---

# Spec: The audit log says what answered a control request

Stacked on `fix/48-dialog-stray-key`: the dialog side changes #48's dialog,
not `master`'s. #48 merges first; this branch is rebased onto `master`
after.

## Design

### 1. What an answer records

`control._answer` (`control.py:361`) gains the answerer's details, and its
`confirmed` / `denied` audit line carries them alongside the existing
`request`, `by` and `holder`:

| field | value |
|---|---|
| `via` | `dialog-key`, `dialog-click`, or `cli` |
| `key`, `mods` | for `dialog-key` only: the Qt key code and modifier bits, as ints |
| `pid` | `os.getpid()` of the process running `_answer` |
| `chain` | up to three ancestors, nearest first, as one string, e.g. `.quickshell-wra < systemd` or `bash < node < tmux: server`. Each name is read from `/proc/<pid>/comm`, following `PPid:` in `/proc/<pid>/status`. Best effort: an unreadable step ends the chain, and a failure never fails the answer. |
| `id_given` | whether the caller passed an explicit request id |

There is no `dialog-timeout`: a lapsed request is expired by `control.py`
itself, and that is already audited as `expired`.

`chain` is a string, not a list, because `render_audit` prints `k=v` pairs
and a list would print as Python repr. Three steps are enough to tell the
shell, an agent's terminal and an SSH session apart without logging a
process tree.

### 2. How the path reaches `_answer`

- **CLI:** `control` gains `--via {dialog-key,dialog-click}`, plus `--key N`
  and `--mods N` (ints).
  - Omitting `--via` means `cli`. Nothing can *claim* `cli` explicitly; it
    is only ever the default.
  - `api.run('control', …)` validates them: `via` in the enum, and
    `key`/`mods` as non-negative ints present only with `dialog-key`.
  - They are passed into `confirm_request` / `deny_request`, which take
    keyword arguments and hand them to `_answer`.
- **The dialog** (`plugin/AgentConfirmDialog.qml`, as of #48):
  - `answer(mode)` becomes `answer(mode, via, key, mods)`. It runs
    `control <mode> <id> --via <via>`, adding `--key`/`--mods` for keys.
  - The `Keys.onPressed` call at line 100 passes `"dialog-key", event.key,
    event.modifiers`.
  - The Allow and Deny clicks (lines 142 and 149) pass `"dialog-click"`.
- **MCP:** unchanged. Agents still cannot confirm or deny at all.

### 3. Confirm needs an id (intent Q1)

`api.run('control', {'mode': 'confirm'})` without an `id` raises
`MirrorError('invalid', 'confirm needs the request id (ai-mirror status
shows it): a confirm must name what it approves')`. `deny` keeps defaulting
to the waiting request. The dialog always passes the id, so it is
unaffected.

### 4. Evidence, not proof

Every field is reported by, or observed from, a process on the user's
account, so a hostile process can lie in all of them. The `audit` verb's
docstring and `docs/usage.md` say so in one sentence: "`via` and `chain`
show what answered, as that process reported it; on a shared account they
are evidence, not proof (see AGENTS.md on the gate)."

### 5. Reading it

`render_audit` already prints every field as `k=v`, so the new fields
appear without a change. Old entries simply lack them. The `audit --json`
output gains the fields as they are.

## Alternatives rejected

- **The dialog writes the audit line itself.** It would need write access to
  the log from QML, and two writers. The CLI is already the single writer.
- **Logging the full process tree, or argv.** argv can contain anything,
  including secrets in a terminal command line. Three `comm` names are
  enough to tell the answerer's kind.
- **Requiring an id for `deny` too.** Denying blindly is always safe, and a
  human mashing `control deny` in a panic should work.
- **Refusing confirms whose `chain` doesn't look like the dialog.** That is
  enforcement built on forgeable data. It would claim a boundary that does
  not exist, which AGENTS.md says not to add.

## Risks

- **Breaking change:** `ai-mirror control confirm` with no id now fails.
  Anyone who confirms from a terminal must pass the id. The error says
  where to find it.
- **`/proc` on other systems:** best effort, and the chain is simply shorter
  or absent. Linux-only is fine; the project is Hyprland-only.
- **The QML change is untestable outside the shell.** The existing
  `test_confirm_wiring.py` (#48) gains assertions that every
  `answer("confirm"…)` / `answer("deny"…)` call passes a `via`.

## Verification

- Unit tests (`tests/test_audit_answerer.py`, with `guard` armed and no
  desktop):
  - A CLI confirm with an id gives `via=cli`, `id_given=true`, an int `pid`,
    and a non-empty `chain` string.
  - A dialog key confirm records `key` and `mods`.
  - `--via cli` passed explicitly is rejected, as are `--key` without
    `dialog-key` and a `via` outside the enum.
  - A confirm without an id gives `invalid`, and the state is unchanged.
  - A deny without an id still works, with `id_given=false`.
  - An unreadable `/proc` gives a shorter chain, and the confirm still
    succeeds.
  - An old-format entry renders unchanged.
- `test_confirm_wiring.py`: every QML `answer(` call passes a via.
- The existing audit tests (#44) pass unchanged. `nix flake check` is green.
- **Live, together with #48's remaining live check:** a confirm by key, by
  click and from a terminal each show a distinct `via` and `chain` in
  `ai-mirror audit`. If a no-input grant like 15:45 recurs, its line says
  which path it came from.
