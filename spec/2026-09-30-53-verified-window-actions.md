---
status: draft
issue: 53
intent: intent/2026-09-30-53-verified-window-actions.md
---

# Spec: window says whether the action happened

## Design

The `window` branch of `api.run` (`src/ai_mirror/api.py:145`) becomes read,
act, confirm. The owner and generation gate above it is unchanged.

### 1. Read before acting

`host.windows()` is read once and the target is the row whose `address`
matches.

- **No such window:** raise `MirrorError('no_such_window', ...)` and dispatch
  nothing. Today this dispatches, and Hyprland may answer `ok`.
- **`resize` or `center` on a tiled window** (`floating` false): raise
  `MirrorError('invalid', 'resize/center applies to floating windows; this one
  is tiled. Float it first; do not retry as is.')`. Neither can do what was
  asked on a tiled window.

### 2. Skip what already holds

If the requested state already holds, dispatch nothing and return
`changed: false, verified: true`:

| action | already holds when |
|---|---|
| `focus` | `host.focused_address() == address` |
| `float` with `enabled` | `row['floating'] == enabled` |
| `workspace` | `row['workspace'] == workspace` (names; `"3"`, `"special:x"`) |
| `resize` | `row['size'] == [w, h]` |

`close`, `center`, `fullscreen` and a bare `float` never skip.

### 3. `float` takes `enabled`

`enabled: bool` is optional. Without it, `float` toggles, exactly as now.
With it, step 2 decides: if the state already matches, nothing is sent;
otherwise the existing toggle dispatcher is sent. No new token reaches Lua.
`host.window_dispatch` does not change for this. Because the check runs after
the read, the toggle still lands on the intended state even if the first call
was ambiguous.

### 4. Confirm after acting

After `host.ctl('dispatch', ...)`, poll `host.windows()` (plus
`host.focused_address()` for `focus`) until the check for the action holds:

| action | holds when |
|---|---|
| `focus` | focused address is `address` |
| `close` | no row has `address` |
| `float` | `floating` equals `enabled`, or `not before` when toggling |
| `workspace` | `workspace` equals the requested name |
| `resize` | `size == [w, h]` |
| `fullscreen` | `fullscreen` differs from before |
| `center` | not checked: see below |

For `center`, the expected position depends on reserved areas (the bar),
which `host` does not model. It is dispatched, `after` is read once, and the
result says `verified: null` with `before`/`after`. That is honest rather
than a guess.

The polling loop is taken out of `wait.until` as
`wait.poll(check, timeout) -> dict`, which returns `result`
(`confirmed` / `not_confirmed` / `unavailable`), `polls` and `waited_ms`.
`until` then calls it. The three-way distinction and its reasons (a failed
read is not an absence; `nan` is refused) stay in one place.
`wait._timeout` gains a `default` parameter. `window` uses **1.5 s** (intent
Q1) and accepts `timeout` with the same bounds as `wait` (0.1 to 30 over
MCP).

### 5. Result

Success, from `api.run` (the CLI prints it; MCP returns it):

```json
{"ok": true, "action": "float", "address": "0x…", "changed": true,
 "verified": true, "before": {…row…}, "after": {…row…}, "waited_ms": 60}
```

`before`/`after` are `host.windows()` rows. `after` is `null` after a close.

Failures raise `MirrorError`, whose `details` both MCP (`isError: true`) and
the CLI already print:

- `not_confirmed`: dispatched, but the state did not hold before the
  deadline. The message says it may still land, and to call `windows` before
  retrying (the same warning `wait` gives). `details` carries `before`,
  `after` and `waited_ms`.
- `unavailable`: dispatched, but the state could not be read afterwards.
  `details` carries `before` and the reason.

### 6. `pid` in `windows`

Add `'pid'` to the keys in `host.windows()` (`host.py:84`). Report only
(intent Q2). Measured on this host: three windows share pid 301556, so a pid
names a process, not a window. That is a second reason not to enforce it.

### 7. Surfaces

- `mcp.py`: add `enabled: boolean` and `timeout: number (0.1–30)` to the
  `window` schema. The description says `float` sets the state when `enabled`
  is given and toggles otherwise, and that the result is checked against the
  compositor.
- `cli.py`: add `--enabled/--no-enabled` (`BooleanOptionalAction`, default
  unset) and `--timeout`.
- `docs/usage.md`: the `window` row, the CLI line, `pid` in the `windows` row,
  and the result and error codes.

## Alternatives rejected

- **Hyprland's event socket instead of polling.** A state that already holds
  produces no event, and each read is about 10 ms. This is the same reasoning
  as `wait.py`'s docstring.
- **Leave confirmation to the agent via `wait`.** `wait`'s checks cannot
  express "this address is floating", and it puts the same work on every
  agent. #8 says the tool should ask the compositor.
- **Lua `action = "enable"/"disable"` for float.** Unmeasured on 0.56, and it
  adds a token to Lua. Reading the state and then toggling reuses the
  existing, tested dispatcher.
- **Enforcing address + pid.** Decided against in the intent, and pids are
  shared across windows.
- **Computing the centre from monitor geometry.** It needs reserved areas we
  do not read. It would be a confident wrong answer.

## Risks

- **Behaviour change:** callers that got a false `ok` now get
  `not_confirmed`. That is the point, but scripts that ignore errors will
  notice. `tests/smoke.py` uses `focus` and `close`, and both should verify.
- **`fullscreen` toggle semantics on 0.56 are not measured.** The check is
  "the state changed", which holds for a toggle and for a set. The first live
  run confirms it. If the dispatcher sets rather than toggles, the check
  becomes "equals the requested mode" (1 = maximized, 2 = fullscreen) and the
  plan records that as a deviation.
- **Hyprland clamps a resize to the app's minimum size** → `not_confirmed`,
  with `after.size` showing what it got. That is correct and truthful.
- **An app that asks "save changes?" on close** → `not_confirmed`. Correct.
- **Latency:** a successful action now costs one read before and roughly
  1–3 reads after (about 10 ms each). A failed one costs the whole 1.5 s.

## Verification

- Unit tests (`tests/test_window_verified.py`, no Wayland, `guard` armed,
  `host.ctl` stubbed with a scripted `clients` sequence):
  - For each action, the confirmed path returns `verified: true` and sends
    exactly one dispatch.
  - A state that never changes gives `not_confirmed`, with `before`/`after`
    in `details`.
  - Each already-holds case sends no dispatch.
  - An unknown address gives `no_such_window` and no dispatch.
  - `resize`/`center` on a tiled window gives `invalid` and no dispatch.
  - `float` with `enabled: true` twice leaves it floating, with one dispatch
    in total.
  - A read failure after dispatch gives `unavailable`.
  - `pid` is present in `windows()` rows.
  - The MCP schema accepts `enabled` and `timeout` and rejects
    `timeout: nan`.
- The existing `wait` tests pass unchanged after `poll` is extracted.
- `python3 -m unittest discover -s tests -v` and `nix flake check` are green.
- Live (`tests/smoke.py` plus one manual run on a scratch workspace):
  `float --enabled` twice, then `fullscreen` to settle the toggle question,
  then `close` on a window that prompts, which should report
  `not_confirmed`.
