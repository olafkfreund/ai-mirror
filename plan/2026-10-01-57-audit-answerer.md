---
status: approved
issue: 57
spec: spec/2026-10-01-57-audit-answerer.md
---

# Plan: The audit log says what answered a control request

Branch `fix/57-audit-answerer`, stacked on `fix/48-dialog-stray-key` at
`7d70125`. #48 merges first; then rebase onto `master`. Line numbers are as
of `925745e`.

## Approved decisions (self-contained)

- **What each `confirmed` / `denied` audit line gains,** beside `request`,
  `by` and `holder`:
  - `via`: `dialog-key`, `dialog-click` or `cli`;
  - `key` and `mods` (ints, for `dialog-key` only);
  - `pid` (`os.getpid()`);
  - `chain`: up to three ancestor `comm` names, nearest first, joined with
    `" < "`, read best effort from `/proc`;
  - `id_given` (bool).
- **There is no `dialog-timeout`,** since `expired` is already audited by
  `control.py`.
- **How the path is passed:** the CLI `control` takes `--via
  {dialog-key,dialog-click}`, `--key N` and `--mods N`.
  - No `--via` means `cli`. `cli` cannot be passed explicitly.
  - `api.run` validates them. `key`/`mods` are non-negative ints, allowed
    only with `dialog-key`.
- **`confirm` requires an explicit id.** Without one: `MirrorError('invalid',
  'confirm needs the request id (ai-mirror status shows it): a confirm must
  name what it approves')`, with no state change. `deny` keeps defaulting to
  the waiting request.
- **The dialog** passes `--via` on every answer, and `--key`/`--mods` on a
  key answer.
- **MCP is unchanged.**
- **Every field is evidence, not proof,** and the docs say so in one
  sentence. Nothing enforces anything based on these fields.
- `render_audit` is unchanged: it already prints `k=v`. Old entries still
  render.

## Steps

1. **`src/ai_mirror/control.py:361-393`: record the answerer.**
   - Add a module-level `_chain(pid=None, depth=3) -> str | None`. Walk
     `PPid:` in `/proc/<pid>/status` and read each `/proc/<ppid>/comm`
     (stripped), nearest first. Stop at pid ≤ 1 or on any `OSError` /
     `ValueError`. Return `' < '.join(names)`, or `None` if there are none.
   - `_answer(request_id, granted, *, via='cli', key=None, mods=None,
     id_given=True)` adds `via`, `key`, `mods`, `pid=os.getpid()`,
     `chain=_chain()` and `id_given` to the `audit(...)` call at line 368.
     Pass `None`s through; `render_audit` already skips `None`.
   - `confirm_request(request_id, **answerer)` and
     `deny_request(request_id, **answerer)` forward them.
   - → verify: step 5's tests.
   - Traps:
     - `_chain` must never raise into `_answer`: catch `OSError`,
       `ValueError` and `IndexError`.
     - Do not log argv or `cmdline`, only `comm`.
     - The audit call stays inside the lock, where it is now.

2. **`src/ai_mirror/api.py:192-197`: validate and require the id.**
   - After the `by == 'agent'` check:
     - `via = args.get('via')` must be `None` or one of `dialog-key` /
       `dialog-click`, else `ValueError('via must be dialog-key or
       dialog-click')`;
     - `key` and `mods` must be `None` or non-negative ints (`type(x) is
       int`), and present only if `via == 'dialog-key'`, else `ValueError`.
   - `given = bool(args.get('id'))`. If `mode == 'confirm' and not given`,
     raise the `invalid` error above.
   - Call `confirm_request` / `deny_request` with
     `via=via or 'cli', key=…, mods=…, id_given=given`.
   - → verify: step 5.
   - Traps:
     - The CLI reaches here without MCP validation, so validate here.
     - Keep the `not_owner` refusal for `by == 'agent'` first, unchanged.

3. **`src/ai_mirror/cli.py:67-70`: the flags.**
   - Add `--via` with `choices=['dialog-key', 'dialog-click']`, plus
     `--key` (`type=int`) and `--mods` (`type=int`).
   - Update `id`'s help: "the request id; required for confirm, optional
     for deny (the waiting one)".
   - → verify: `./bin/ai-mirror control --help` shows them.
   - Traps: `cli.main` drops `None`s, which is what we want.

4. **`plugin/AgentConfirmDialog.qml`: pass the path.**
   - Line 29: `function answer(mode, via, key, mods)`. Build
     `["control", mode, String(request.id), "--via", via]`, and append
     `"--key", String(key), "--mods", String(mods)` when `via ===
     "dialog-key"`.
   - Line 100: `root.answer(a, "dialog-key", event.key, event.modifiers)`.
   - Line 142: `root.answer("deny", "dialog-click")`.
   - Line 149: `root.answer("confirm", "dialog-click")`.
   - → verify: `nix build .#plugin`, then `grep -c '"--via"'
     result/AgentConfirmDialog.qml` gives 1.
   - Traps:
     - The id is already always passed, so confirm-needs-id cannot break
       the dialog. Keep `String(request.id)`.
     - Do not touch #48's rule, grace, resets or pointer arming.

5. **Tests.**
   - `tests/test_audit_answerer.py` (new), subclassing `test_invariants.Base`
     (guard armed). Ask for control with `control.set_owner('agent', 'agent')`,
     then answer through `api.run('control', …, by='human')`. Read the result
     back with `control.read_audit(0)['entries'][-1]`. Cases:
     - A CLI confirm with an id gives `via == 'cli'`, `id_given is True`,
       an int `pid`, and `chain` as a str or `None`.
     - `via='dialog-key', key=65, mods=0` is recorded.
     - `via='cli'` explicitly → `ValueError`.
     - `key` given with `dialog-click` → `ValueError`.
     - `via='bogus'` → `ValueError`.
     - A confirm without an id → `MirrorError` code `invalid`, and
       `read_state()['owner'] == 'pending'` afterwards.
     - A deny without an id succeeds and records `id_given is False`.
     - With `/proc` reads patched to raise `OSError`, the confirm still
       succeeds and `chain` is `None`.
     - An old-style entry (no new fields) renders through
       `cli.render_audit` without error.
   - `tests/test_confirm_wiring.py`: assert that every `root.answer(` call
     in the QML passes a via. Use a regex: every `root.answer\(` match is
     followed by `"dialog-`.
   - → verify: `python3 -m unittest discover -s tests` → all OK;
     `node --test tests/test_confirm_keys.mjs` → unchanged.
   - Traps:
     - The tests must not reach the desktop. `set_owner` is already covered
       by `Base`'s stubs.
     - `test_audit.py` (#44) must stay unchanged and green.

6. **Docs.**
   - `docs/usage.md:89`: `ai-mirror control confirm ID | deny [ID]`.
   - `docs/usage.md:131` and `README.md:160`: `control confirm` becomes
     `control confirm ID`, with "(the id is in `ai-mirror status`)".
   - `README.md:189`: unchanged in meaning; it already says a shell can
     confirm.
   - Add one sentence to `read_audit`'s docstring and to `docs/usage.md`'s
     audit text: "`via` and `chain` show what answered, as that process
     reported it; on a shared account they are evidence, not proof."
   - → verify: read back.
   - Traps: do not touch `gotchas.md` (index cap).

7. **Live check.** Done together with #48's R5 and #58's check:
   - a key confirm, a click confirm and a terminal `control confirm ID`
     each show a distinct `via` and `chain` in `ai-mirror audit`;
   - a bare `control confirm` is refused.
   - → verify: audit lines pasted into the PR.

## As built (independent review: no blocking findings)

- `_chain` also catches `StopIteration`, because `next()` has no default when
  a `status` has no `PPid:` line. "Never raises" requires it.
- `test_confirm_wiring.py`'s existing click assertion was updated for the new
  `answer(..., "dialog-click")` call, and the wiring test pins exactly three
  `root.answer(` calls.
- The `/proc` failure test patches `open` only for `/proc/` paths. Patching
  every `open` broke the state-file lock.
- After review: tests for the CLI flags reaching `api.run`, for argparse
  refusing `--via cli`, and for `key`/`mods` without `via` being refused.
- Not done (review nit): `control agent|off --via …` ignores the flags rather
  than refusing them. Nothing is audited on that path.

## Tests

```sh
python3 -m unittest discover -s tests       # all OK
node --test tests/test_confirm_keys.mjs    # unchanged
nix flake check
```

## Rollback

Revert the implementation commits. Old and new audit lines both remain
readable, because the fields are additive. A bare `control confirm` works
again after the revert.

## Live check results (2026-10-01, p620, Hyprland 0.56, three monitors)

The test build combined #48, #57 and #58 (`test/live-48-57-58`). The human answered every case, and `ai-mirror audit` recorded each answer:

| case | human input | outcome | audit |
|---|---|---|---|
| wait about 2 s, then `a` | key | granted | `confirmed via=dialog-key key=65 mods=0` |
| moved the mouse, clicked Allow | click | granted | `confirmed via=dialog-click` |
| `→` after the grace | key | denied | `denied via=dialog-key key=16777236` (Right) |
| typed "hello" | key | denied | `denied via=dialog-key key=72` (H) |
| `Esc` (earlier build) | key | denied | — |
| `a` straight away (earlier build) | key | denied | — |

- The dialog appeared **0.14 s** after the request, with **at most one**
  `omarchy-ai-mirror-confirm` layer at a time (before #58 there were three).
- The audit `chain` for dialog answers is
  `.quickshell-wra < omarchy-launch- < .Hyprland-wrapp`.
- The two "no-input" grants earlier in the day (15:45, on a pre-#57 build)
  could not be traced retroactively. Every grant in this run matched a
  human key or click.
- The test dialog was loaded by repointing the Home Manager plugin link and
  running a foreground shell reload, then restored the same way. A link swap
  alone re-runs cached QML.
