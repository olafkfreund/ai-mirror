---
status: draft
issue: 81
spec: spec/2026-10-28-81-stale-hyprland-signature.md
---

# Plan: ai-mirror keeps working after Hyprland restarts

**Implementer: the `coder` agent.** The plan has 6 file-editing steps across 6 files. The session
model reviews with a fresh Opus agent, given only this plan and `git diff`.

## Approved decisions (from the spec)

1. **hyprctl finds the live instance.** Measured on p620 (Hyprland 0.56.0): `hyprctl instances
   -j` lists only live instances, even with a stale or unset signature, because it checks each
   lock file's pid. It scans only this user's `$XDG_RUNTIME_DIR/hypr/`. `WAYLAND_DISPLAY` stays
   `wayland-1` across restarts; only the signature goes stale.
2. **One hook, in `host.ctl`.** When a call fails because the instance is gone (`Couldn't
   connect` / `HYPRLAND_INSTANCE_SIGNATURE was not set`), it resolves once and retries once. Any
   other failure is raised unchanged. A dispatch is retried only after a connect failure, which
   means it never ran.
3. **The pick is deterministic:**
   1. the inherited signature, if listed;
   2. else the signature in `systemctl --user show-environment`, if listed;
   3. else the only listed instance;
   4. else refuse.
4. **The environment is the cache.** The pick goes into `os.environ`, together with
   `WAYLAND_DISPLAY` from `wl_socket` when that differs. Children (`grim`, `wl-copy`, the helper,
   `index.sh`) inherit it. Nothing re-resolves until the next lost-instance failure, so there is
   no polling.
5. **The switch is audited** as `instance-changed`, with `from` and `to`.
6. **Decided: revoke.** A grant, and a pending request, is stamped with its instance. When the
   stamp differs from the current instance, the grant is revoked: owner off, generation bumped,
   a11y restored, `why` "Hyprland restarted since control was granted; ask again". A grant
   without a stamp (written before this change) is kept.
7. **Errors.**
   - No live instance: `unavailable`, "Hyprland is not running for this user (hyprctl instances
     is empty)".
   - Several and no rule picks one: `unavailable`, "N Hyprland instances are running (<sigs>);
     set HYPRLAND_INSTANCE_SIGNATURE to the one to drive".
   - `doctor` reports `resolved: {from, to}` after a resolve, or `stale` (with the restart hint)
     when resolving fails.
8. **`index.sh` gets the same retry** for `hyprctl` argv only.
9. **Decided: ai-mirror only.** Refreshing the variable in herdr panes is nixarchy's, as a separate
   issue.

## Steps

1. **`src/ai_mirror/host.py:12-23` (`ctl`) — resolve and retry.**
   - Add `LOST = ("Couldn't connect", 'HYPRLAND_INSTANCE_SIGNATURE was not set')`. A failure is
     *lost* when its stderr/stdout contains either string.
   - Add `resolve() -> tuple[str | None, str] | None`:
     - runs `subprocess.run(['hyprctl', 'instances', '-j'], …, timeout=5)` and picks by decision
       3 (systemd: `systemctl --user show-environment`, parse the `HYPRLAND_INSTANCE_SIGNATURE=`
       line, ignore failures);
     - sets `os.environ` (decision 4);
     - returns `(old, new)` when it changed something, `None` when the inherited value was
       already live;
     - raises `RuntimeError('Hyprland: …')` with the decision 7 wording when nothing can be
       picked.
   - Add a module hook `on_switch = None` (a callable `(old, new)`), called after a change, and a
     module flag `verified = False`, set to `True` after any successful `ctl` call.
   - In `ctl`: run as today. On a *lost* failure, call `resolve()` and run the same argv once
     more. Otherwise raise as today. Keep the dispatch guard and the dispatch `ok` check as they
     are.
   - Verify: `python -m unittest tests.test_instance_resolve` (step 6).
   - Traps:
     - `host` must not import `control` (control imports host). Hence the `on_switch` hook.
     - Keep `timeout` semantics: the retry uses the same `timeout`.
     - Don't resolve on a non-lost failure. A real dispatch error must not run twice.

2. **`src/ai_mirror/control.py` — audit the switch, stamp and check grants.**
   - After the imports: `host.on_switch = lambda old, new: audit('instance-changed', **{'from':
     old, 'to': new})`.
   - `set_owner` (`:306`), the `pending` dict (`:319`): add `'instance':
     os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')`.
   - `_answer` (`:386`), `granted_state` (`:403`): add the same `instance` field. Stamp it
     **after** `_baseline_layers()`, which calls `host.ctl` and so has made the signature live.
   - `read_state` (`:224`): after the lapse check, if `owner` is `agent` or `pending`, the state
     has an `instance`, **`host.verified` is true**, and `state['instance'] !=
     os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')`, then revoke under `locked('control')`.
     Re-read the state first, as the lapse path does: `audit('instance-changed-revoke', …)`,
     `_a11y_restore(...)`, and `_write({'owner': 'off', 'generation': +1, 'since': stamp(),
     'enabled_by': None, 'why': RESTARTED})`. Add `RESTARTED = 'Hyprland restarted since control
     was granted; ask again'` next to `LAPSED` (`:100`).
   - Verify: the step 6 grant tests.
   - Traps:
     - **The `host.verified` guard is required.** The grant is stamped by the answering process
       (the bar's CLI), whose environment is fresh. An MCP server that hasn't made a successful
       `hyprctl` call yet still holds the old value, and without the guard it would revoke a
       valid grant.
     - `read_state` is called everywhere, including the bar. Compare only the environment: no
       `hyprctl` call in `read_state`.
     - `require_agent` already maps owner off + `why` to `not_owner`. No change there.

3. **`src/ai_mirror/index.py:51-57` (`sh`) — the same retry for `hyprctl`.**
   - When `argv[0] == 'hyprctl'` and the failure text matches `host.LOST`, call `host.resolve()`
     and run once more. Import `host` locally inside the branch, so the module's import graph
     stays as is.
   - Verify: a step 6 test with `subprocess.run` faked.
   - Traps: only `hyprctl`. Other `sh()` commands are unchanged.

4. **`src/ai_mirror/api.py:133-158` (`doctor`) — say what happened.**
   - Before `host.focused_address()`, note `before = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')`.
     After success, if the value changed, add `report['resolved'] = {'from': before, 'to': …}`.
   - On failure, if `before` is set, add `report['stale'] = before`, and the hint "Hyprland
     restarted after this process started; it now finds the running instance itself. If this
     persists, restart the MCP server". Keep the `unset` branch for a missing value.
   - Verify: the step 6 doctor tests; `ai-mirror doctor` on p620 shows `ok: true`.
   - Traps: `tests/test_reporting_truth.py:186-190` asserts the `unset` report. Keep it passing.

5. **`docs/usage.md:130` — troubleshooting line.** Below the existing `doctor`/`unset` bullet,
   add one bullet: after a Hyprland restart ai-mirror finds the running instance itself, and
   `doctor` shows `resolved`; a grant made before the restart is revoked ("ask again").
   - Verify: read it back.
   - Traps: none.

6. **`tests/test_instance_resolve.py` — new.** Use `unittest`, `patch.object(host, …)`,
   `patch.dict(os.environ, …)`, a fake `subprocess.run` keyed on argv, and the state-file test
   setup from `tests/test_grant_ownership.py`. Cases:
   - stale signature → the first `hyprctl` fails `Couldn't connect`, `instances` lists one, the
     retry succeeds, `os.environ` holds the new value, and `on_switch` gets `(old, new)`;
   - unset → same;
   - several listed, one equal to the systemd value → that one; several, none matching → the
     `unavailable` text, environment unchanged;
   - empty list → "not running";
   - a dispatch returning an error that isn't lost → raised, with `instances` never called;
   - a grant stamped A, environment B, `host.verified = True` → `read_state` revokes with
     `RESTARTED`, generation +1; the same with `verified = False` → kept;
   - a grant without `instance` → kept; a pending request stamped A, environment B → revoked;
   - `doctor`: `resolved` after a resolve, `stale` when resolving fails;
   - `index.sh('hyprctl', …)` retries; `index.sh('ls')` doesn't.
   - Verify: `python -m unittest discover -s tests` passes in full.
   - Traps:
     - Reset `host.verified` and `host.on_switch` in `tearDown`, since they are module state.
     - Never call the real `hyprctl` or `systemctl`.

## Tests

| Command | Expected |
|---|---|
| `python -m unittest discover -s tests` | all pass, including the new file and `test_reporting_truth` |
| `nix flake check` | passes (CI #47) |
| p620: `HYPRLAND_INSTANCE_SIGNATURE=<Oct 22 value> ai-mirror doctor` | `ok: true`, `resolved: {from: <old>, to: <live>}` |
| p620: the MCP server started with the old value → `status`, `screenshot` | work; `ai-mirror audit` shows `instance-changed` |
| p620: grant control, restart Hyprland, call `input` | `not_owner`, "Hyprland restarted since control was granted; ask again"; `control agent` then works |

## Rollback

Revert the implementation commit(s). Behaviour returns to today: a stale signature fails with the
socket error until the process is restarted with the right environment. The state file stays
compatible both ways: an `instance` field is ignored by older code.
