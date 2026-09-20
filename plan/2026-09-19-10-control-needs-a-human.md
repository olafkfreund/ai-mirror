---
status: approved
issue: 10
spec: spec/2026-09-19-10-control-needs-a-human.md
---

# Plan: an agent cannot take control without a human confirming it

## The approved decisions, carried

Implementable without opening the intent or the spec.

**What the gate protects, and what it does not.** Everything here runs as one
user. An agent with a shell can write our state file, run our CLI, and click a
prompt with the same virtual-pointer protocol `ai-mirror-input` uses. So the
gate is **unforgeable only for agents that reach ai-mirror through MCP alone**
(no shell). For the rest it turns a silent capability into a deliberate,
visible, logged act. The owner accepted that limit. Do not add machinery
claiming more.

**`control mode=agent` stops granting.** From every caller — MCP, CLI, API,
all of which pass through `api.run` — it writes a *pending* request and
returns `{"owner": "pending", "request": "<id>"}`. The caller polls `status`.
`require_agent` already refuses anything but `owner == "agent"`, so it stays
the single enforcement point: no new checks at the action sites.

**The prompt is ai-mirror's own bar widget,** not a notification. It already
watches `state.json`, it is ours, and it **fails closed**: no widget, no
prompt, request expires, control stays off, and the refusal says to enable the
widget.

**`confirm` / `deny` are CLI-only.** They are not MCP tools, the `control`
tool keeps only `mode`, and `api.run` refuses them when `by == 'agent'`. That
is what an MCP-only agent cannot reach.

**Timeouts, decided.** A request expires 30 s unanswered (checked lazily on
read; no timer process). A grant ends at the first of: the MCP server exiting
(existing, `mcp.py:251`), **10 minutes with no `input`/`window`/`launch`/
`a11y_act`**, or a revoke.

**Never prompts:** `control off`, the kill switch, and a closing MCP server.
They set `off` directly and clear any pending request.

**Watching is visible, not gated.** Observing ops stay ungated; when
`by == 'agent'` they touch `$XDG_RUNTIME_DIR/ai-mirror/watching`, and the
widget shows a steady neutral mark while that mtime is < 5 s old. Red and
pulsing stay reserved for control.

**Audit:** one JSON line per request, confirm, deny, expiry and revoke in
`$XDG_RUNTIME_DIR/ai-mirror/audit.jsonl`. Runtime-dir only, gone at logout.

**Licence:** `LICENSE` and `NOTICE` in all three outputs.

## Where the state lives

All of it under `control.root()` — `$XDG_RUNTIME_DIR/ai-mirror`, already
created `0700` by `root()`, so the files inherit a private directory:

| Path | Written by | Mode | Contents |
|---|---|---|---|
| `state.json` | `set_owner`, `confirm_request`, `deny_request`, expiry | 0600 (`atomic_write_json` chmods) | adds `request` (`{id, by, since, expires}`) when pending, and `last_input` when granted |
| `watching` | `api.run` before an observing op with `by == 'agent'` | 0600 | empty; the mtime is the signal |
| `audit.jsonl` | every control event | 0600 | one JSON object per line |

Nothing new is created outside that directory, and nothing persists across a
logout. The widget learns of a request through the **`FileView` on
`state.json` it already has** (`plugin/Widget.qml:24-33`, `watchChanges:
true`) — no new IPC, no socket, no polling loop. `watching` is an mtime, so it
needs a 1 s `Timer` in the widget rather than a watch (the file is touched
repeatedly, and inotify on an mtime-only change is noisier than a cheap stat).

## Steps

1. `src/ai_mirror/control.py`: `set_owner('agent', by)` writes the pending
   request instead of granting — `{'owner': 'pending', 'generation': n+1,
   'request': {'id': secrets.token_hex(8), 'by': by, 'since': …, 'expires':
   <now+30>}}` — and returns it. `set_owner('off', …)` clears any request and
   keeps today's behaviour, including `signal_servers()`. Both keep writing
   under `locked('control')`.
   → verify by `ai-mirror control agent` printing `"owner": "pending"` with a
     request id, and `ai-mirror status` still reporting `pending`

2. `src/ai_mirror/control.py`: `read_state()` expires lazily — a `pending`
   state whose `expires` has passed reads back as `{'owner': 'off'}`, and the
   expiry is written (and audited) once, under the lock. Every caller of
   `read_state` gets this for free, which is why there is no timer.
   → verify by writing a state with `expires` in the past and seeing
     `ai-mirror status` report `off`

3. `src/ai_mirror/control.py`: `confirm_request(id)` and `deny_request(id)`.
   `confirm` requires a pending, unexpired request with that exact id, then
   writes `{'owner': 'agent', 'enabled_by': 'human-confirmed', 'request_by':
   <original by>, 'last_input': now, 'generation': n+1}`. A wrong, expired or
   already-answered id raises `MirrorError('bad_request')`. `deny` sets `off`.
   Both audit.
   → verify by confirming a real request from a second terminal and watching
     `status` flip to `agent`

4. `src/ai_mirror/control.py`: idle expiry in `require_agent` — when
   `now - last_input > 600`, set `off` (audited) and raise `not_owner`.
   `run_batch` and the other mutating paths refresh `last_input`; do it in
   `require_agent` itself so every mutating op refreshes by construction
   rather than per call site.
   → verify by a test with an injected clock; by hand, a grant left idle for
     ten minutes reads `off`

5. `src/ai_mirror/control.py`: `audit(event, **fields)` appending one JSON
   line to `audit.jsonl` (open `'a'`, `0600`). Called from request, confirm,
   deny, expiry, idle expiry and revoke.
   → verify by `wc -l` growing by exactly one per event

6. `src/ai_mirror/api.py`: `control` op accepts `mode` in
   `{'agent', 'off', 'confirm', 'deny'}`; `confirm`/`deny` raise
   `MirrorError('not_owner', …)` when `by == 'agent'`, with a message saying
   a human answers this. Before each observing op (`screenshot`, `clipboard`
   read, `a11y_tree`, `a11y_find`, `index`, `wait`), touch `watching` when
   `by == 'agent'` — one helper call at the top of `run`, not six call sites.
   → verify by `api.run('control', {'mode': 'confirm', 'id': …}, by='agent')`
     raising, and `watching` appearing only for agent reads

7. `src/ai_mirror/cli.py`: `control` takes `agent|off|confirm|deny` and an
   optional id positional (`ai-mirror control confirm <id>`). Keep the JSON
   output shape every other op uses.
   → verify by `ai-mirror control confirm deadbeef` printing a `bad_request`
     error rather than a traceback

8. `src/ai_mirror/mcp.py`: the `control` tool's description says asking now
   *requests* control and the human is asked; poll `status` until `owner` is
   `agent` or `off`, with backoff, and never retry blindly on `off`. Same
   change in `INSTRUCTIONS` — it currently says "Call control with mode=agent
   before acting", which is exactly the instruction that must change.
   `TOOLS` gains nothing: `confirm` and `deny` must not appear.
   → verify by `tools/list` over stdio showing no confirm tool and the new
     wording

9. `plugin/ConfirmDialog.qml`: new. A layer-shell window on the focused
   output, keyboard focus, shows `by` and a countdown from `expires`, buttons
   **Deny** (default, and Escape) and **Allow**, running
   `["control", "deny"|"confirm", id]` through the existing `Command.qml`.
   Opened from `Widget.qml` when `state.owner === "pending"`, closed when it
   is not.
   → verify by hand: `ai-mirror control agent` in a terminal pops the dialog

10. `plugin/Widget.qml`: watching state — a 1 s `Timer` stats `watching` and
    exposes `watching: mtime < 5 s`. The mark is red+pulsing for control
    (unchanged), neutral+steady for watching, dim otherwise; tooltip "an agent
    is reading the screen". Click behaviour is unchanged (`off` when on,
    request when off).
    → verify by hand: `ai-mirror screenshot` as an agent shows the neutral
      mark for ~5 s

11. `flake.nix`: install `LICENSE` and `NOTICE` into
    `$out/share/doc/ai-mirror/` and `$out/share/doc/ai-mirror-input/`, and copy
    both into the plugin directory root. Add a check asserting all three
    outputs carry both files.
    → verify by `test -f "$(nix build .#plugin --print-out-paths)/LICENSE"`
      and the same for both programs

12. `docs/usage.md`, `README.md`, `src/ai_mirror/gotchas.md`: the flow is now
    request → human answers → poll `status`. `gotchas.md` is what `index`
    serves, so it is how the habit reaches an agent: say that `control agent`
    returns `pending`, that the answer is a human's, and that a `off` after a
    request means denied — not a reason to retry.
    → verify by `ai-mirror index` containing it

13. `AGENTS.md`: code-map rows for `ConfirmDialog.qml` and the new control
    functions, and one line stating the threat-model limit so the next reader
    does not assume more protection than exists.
    → verify by reading the diff

## Tests

All in `tests/test_invariants.py`, in the existing `Base` style (temp
`XDG_RUNTIME_DIR`, no compositor). Each must be **seen failing on today's
`master` (`295762d`)** before the fix lands, and the red output goes in the PR.

| Case | Red today because |
|---|---|
| `set_owner('agent','agent')` leaves `owner == 'pending'`; `require_agent` still refuses | it grants immediately |
| `set_owner('agent','human')` is pending too (the CLI path) | it grants |
| `confirm` with the right id → `agent`, `enabled_by == 'human-confirmed'` | there is no confirm |
| `confirm` with a wrong id, an expired id, or twice → `bad_request` | there is no confirm |
| `api.run('control', {'mode':'confirm'}, by='agent')` raises; `mcp.TOOLS` has no confirm tool and `control`'s schema has no id | an MCP agent could answer itself |
| a request 31 s old (injected clock) reads back `off` | there is no expiry |
| `require_agent` 10 min after `last_input` (injected clock) → `not_owner`, state `off` | there is no idle expiry |
| a mutating op refreshes `last_input` | the field does not exist |
| `control off` while pending clears `request` and does not prompt | there is no pending state |
| an observing op with `by='agent'` touches `watching`; with `by='human'` it does not | there is no watching file |
| each of request/confirm/deny/expiry appends exactly one `audit.jsonl` line | there is no log |
| flake check: `LICENSE` and `NOTICE` in all three outputs | none ship them |

```sh
python3 -m unittest discover -s tests -v
nix build .#ai-mirror .#ai-mirror-input .#plugin
nix flake check
```

**By hand, on a live session** (no display in the suite, as with the existing
mark): `ai-mirror control agent` pops the dialog; Allow grants and the mark
turns red; Deny and Escape leave it off; an unanswered request expires at the
countdown; `ai-mirror screenshot` as an agent shows the neutral watching mark;
the kill switch still revokes instantly without a prompt.

**The acceptance case that matters:** with the widget **disabled**, ask for
control and confirm it is refused after the timeout with the message naming the
widget. A version that granted control when nobody could see a prompt would
pass every unit test above and be the bug this issue exists to prevent.

## Rollback

`git revert` the implementation commits. State lives only in
`$XDG_RUNTIME_DIR`, so a revert plus a logout (or deleting
`$XDG_RUNTIME_DIR/ai-mirror`) leaves nothing behind: no service, no disk file,
no schema migration. A client mid-request sees `owner: off` and asks again the
old way.

**Dependants to warn:** nixarchy-voice's backend must handle `pending`
(nixarchy-voice#17 gates the whole link off by default), and nixarchy#773
describes this gate as the reason ai-mirror may ship installed.

## Deviations, recorded while implementing

Five, all small, all in the same commit as the code they describe.

1. **`watching` holds the time of the last look, not an empty file.** The plan
   had the widget stat its mtime on a 1 s timer. QML has no stat, and a
   `FileView` cannot see a change in a file whose content never changes, so the
   file holds the unix seconds and the widget reads it the way it already reads
   `state.json`. The 1 s timer stays, but only to age the value out.
2. **`locked()` is re-entrant.** `read_state()` writes a lapsed request under
   the lock, and it is called from inside `set_owner`'s lock; a second `flock`
   on a new fd from the same process would deadlock.
3. **`last_input` is refreshed in `require_agent`** (the decision the plan left
   open), coalesced to once a minute. Writing state.json per input batch would
   make the bar's `FileView` re-parse on every mouse move for no gain against a
   ten-minute limit.
4. **Deny is the default in every direction.** Escape, Return and `D` all deny;
   Allow needs `A` or a click. An Enter left over from whatever had focus must
   not hand an agent the keyboard.
5. **Two more audit events than the table listed:** `off` (a stop, and who did
   it) and `idle` (a grant that timed out), so the log accounts for every
   transition rather than only the answered ones.
