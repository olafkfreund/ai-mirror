---
status: approved
issue: 53
spec: spec/2026-09-30-53-verified-window-actions.md
---

# Plan: window says whether the action happened

Branch: `feat/53-verified-window-actions`.

## Approved decisions (self-contained)

- `window` = read → act → confirm. The owner + generation gate above it
  (`api.py:128-132`) is unchanged.
- **Read first**, via `host.windows()`:
  - Unknown address → `MirrorError('no_such_window', ...)`, no dispatch.
  - `resize` or `center` on a row with `floating` false →
    `MirrorError('invalid', 'resize/center applies to floating windows; this
    one is tiled. Float it first; do not retry as is.')`, no dispatch.
- **Already holds → no dispatch.** Return `changed: false, verified: true`
  when:
  - `focus`: `host.focused_address() == address`
  - `float` with `enabled`: `row['floating'] == enabled`
  - `workspace`: `row['workspace'] == workspace`
  - `resize`: `row['size'] == [w, h]`

  `close`, `center`, `fullscreen` and a bare `float` never skip.
- **`float` + `enabled`:**
  - `enabled` is optional; without it, `float` toggles as today.
  - With it, send the existing toggle dispatcher only when the state differs.
  - No new Lua token. `host.window_dispatch` does not change.
- **Confirm after dispatch** by polling until the check for the action holds:

  | action | holds when |
  |---|---|
  | `focus` | focused address is `address` |
  | `close` | no row has `address` |
  | `float` | `floating == enabled`, or `== not before['floating']` when toggling |
  | `workspace` | the row's workspace is the requested one |
  | `resize` | `size == [w, h]` |
  | `fullscreen` | the row's `fullscreen` differs from `before` |
  | `center` | position not checked: polls until the row exists, `verified: None`; a window that closes is `not_confirmed` after the timeout |

- **Timing:**
  - Default 1.5 s; `timeout` is accepted with `wait`'s bounds.
  - The loop is taken out of `wait.until` into `wait.poll(check, timeout)`.
    `_timeout` gains a `default` parameter.
- **Success result:**
  `{'ok': True, 'action', 'address', 'changed', 'verified', 'before', 'after', 'waited_ms'}`.
  `before`/`after` are `host.windows()` rows, and `after` is `None` once the
  window is gone.
- **Failures:**
  - `MirrorError('not_confirmed', 'did not reach the requested state within
    Ns; it may still land -- call windows before retrying',
    details={'before', 'after', 'waited_ms'})`.
  - `MirrorError('unavailable', <reason>, details={'before'})` when the read
    after dispatch fails.
- `host.windows()` rows gain `pid`. Report only, never enforced: pids are
  shared across windows (measured: three windows on pid 301556).
- New arguments:
  - MCP: `enabled` (boolean) and `timeout` (number, 0.1–30).
  - CLI: `--enabled/--no-enabled` and `--timeout`.
  - Docs updated to match.

## Steps

1. **`src/ai_mirror/wait.py:111-169`: extract `poll`.**
   - `_timeout(value, default=DEFAULT_TIMEOUT)`: return `default` when
     `value is None`.
   - New `poll(check, timeout) -> dict`. `check(budget) -> bool` is called
     with what is left of the deadline (at least 0.1). It returns
     `{'result': 'confirmed'|'not_confirmed'|'unavailable', 'polls',
     'waited_ms'}`, plus `'reason'` (≤200 chars) on `unavailable`.
   - The body is the current loop in `until` (lines 146-169) with
     `held is not absent` replaced by `held`.
   - `until` keeps its validation. It calls `poll(lambda b: check(value, b) is
     not absent, timeout)` and adds `'predicate': name` to the result.
     `until`'s output must be byte-for-byte what it is today.
   - → verify: `python3 -m unittest tests.test_invariants.Wait -v` passes
     unchanged.
   - Traps:
     - Keep the module docstring and the comments on budget and
       could-not-look; they are the reasoning.
     - `nan` must still be rejected by `_timeout`.
     - The `except Exception` catch stays inside `poll`.

2. **`src/ai_mirror/host.py:84`: add `'pid'` to `keys`.**
   - → verify: covered by the step 5 tests.
   - Traps: none. The `[:240]` trim applies to strings only, and pid is an
     int.

3. **`src/ai_mirror/api.py:145-149`: replace the `window` branch** with a call
   to a new module-level `_window(args)` in `api.py`.
   - Validate `enabled` (`None` or `bool`, else `ValueError`) and `timeout`
     (via `wait._timeout(args.get('timeout'), default=1.5)`).
   - Build the dispatcher with `host.window_dispatch(...)` **before** reading
     the state, so bad input fails as `ValueError` exactly as today.
   - Read `rows = host.windows()` and find the row (else `no_such_window`).
     Apply the tiled refusal, then the already-holds table.
   - `host.ctl('dispatch', dispatcher)`.
   - Then `wait.poll(check, timeout)`, where `check` re-reads `host.windows()`
     (and `host.focused_address()` for focus), stores the latest row in a
     closure variable, and applies the confirm table.
   - `center`: after dispatch, poll until the row exists, return `verified: None`,
     `changed: after['at'] != before['at']`.
   - Map `poll` results to the success dict, `not_confirmed` or
     `unavailable`, as above.
   - → verify: `python3 -m unittest discover -s tests -v`.
   - Traps:
     - The `workspace` compare is string to string (`row['workspace']` is
       the name).
     - `size` from hyprctl is a list: compare with `[w, h]`, not a tuple.
     - Do not guard reads. `guard` blocks only `host.ctl dispatch`, and tests
       stub `host.ctl`/`host.windows`.
     - `api.run` is reached by the CLI without MCP validation, so `enabled`
       and `timeout` must be validated here.
     - Keep `_window` small; no class.

4. **`src/ai_mirror/mcp.py:63-66` and `src/ai_mirror/cli.py:82-88`: the new
   arguments.**
   - MCP schema: add `'enabled': {'type': 'boolean'}` and
     `'timeout': {'type': 'number', 'minimum': 0.1, 'maximum': 30}`.
   - MCP description: "float sets floating to enabled when given, toggles
     otherwise. The result is checked against the compositor: verified, or
     error not_confirmed (it may still land -- call windows before retrying).
     resize/center need a floating window."
   - CLI: add `p.add_argument('--enabled', action=argparse.BooleanOptionalAction)`
     and `p.add_argument('--timeout', type=float)`.
   - → verify: `ai-mirror window --help` lists both;
     `mcp.validate('window', {'action': 'float', 'address': '0x1', 'timeout': float('nan')})`
     raises.
   - Traps:
     - `cli.main` drops `None` values (`cli.py:146`), so `--no-enabled`
       (False) survives and an unset flag does not.
     - The MCP `number` type already refuses bool/nan/inf.

5. **`tests/test_window_verified.py` (new): the unit tests.**
   - Subclass `test_invariants.Base` (import it) so `guard` is armed, and
     `grant()` control first.
   - Stub `host.windows` with a scripted sequence of row lists, stub
     `host.focused_address`, and stub `host.ctl` to record dispatches and
     answer `'ok'`.
   - Cases:
     - Confirmed per action, with exactly one dispatch.
     - A state that never changes → `not_confirmed` with `before`/`after` in
       `details` (use `timeout: 0.1`).
     - Each already-holds case sends zero dispatches.
     - Unknown address → `no_such_window` with zero dispatches.
     - Tiled `resize`/`center` → `invalid` with zero dispatches.
     - `float enabled=True` twice (floating after the first) → one dispatch
       in total.
     - `windows` raising after dispatch → `unavailable`.
     - `center` → `verified is None`.
     - A `host.windows()` row built from a fake `clients` reply carries `pid`.
     - `enabled='yes'` → `ValueError`.
     - An MCP `call_tool('window', ...)` failure has `isError` and
       `code == 'not_confirmed'`.
   - → verify: `python3 -m unittest tests.test_window_verified -v`.
   - Traps:
     - Tests must never reach the desktop. Rely on the armed guard and do not
       call `guard.disarm()`.
     - Keep the tests fast: `timeout: 0.1` on the not-confirmed paths.

6. **`docs/usage.md:45,47,91`: update the documentation.**
   - Add `pid` to the `windows` row.
   - The `window` row gains `enabled`, `timeout`, and one line on the result
     (`verified`, `changed`, `before`/`after`) and the errors
     `no_such_window`, `not_confirmed`, `unavailable`.
   - The CLI line gains `[--enabled|--no-enabled] [--timeout S]`.
   - → verify: read it back.
   - Traps: AGENTS.md's code map does not change (no new module).

7. **Live check (manual; moves real windows).** On a scratch workspace the
   human is not using, with control granted:
   - `ai-mirror window float <addr> --enabled` twice → second
     `changed: false`.
   - `ai-mirror window fullscreen <addr>` → `verified: true`. If Hyprland
     *sets* rather than toggles, record it here as a deviation and change the
     check to "equals the requested mode".
   - `ai-mirror window close <addr>` on an editor with unsaved text →
     `not_confirmed`.
   - → verify: outputs pasted into the PR.
   - Traps: re-read `ai-mirror status` for the generation (AGENTS.md), and
     silence notifications first.

## Tests

```sh
python3 -m unittest discover -s tests -v    # all green, including Wait unchanged
nix flake check                              # green
```

## Rollback

Revert the implementation commits. Nothing persists state or changes the
config, so a revert is complete. Callers see the old `{'ok': True}` again.
