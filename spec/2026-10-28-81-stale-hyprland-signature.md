---
status: draft
issue: 81
intent: intent/2026-10-28-81-stale-hyprland-signature.md
---

# Spec: ai-mirror keeps working after Hyprland restarts

## Measured first (2026-10-28, Hyprland 0.56.0, p620)

| Check | Result |
|---|---|
| `$XDG_RUNTIME_DIR/hypr/` | 3 directories: two dead instances (Oct 22, today 07:38) and the live one (07:39) |
| `hyprctl version` with the Oct 22 signature | `Couldn't connect to …/.socket.sock. (4)`, exit 1 |
| `hyprctl instances -j`, signature unset **or stale** | Lists only the live instance: `instance`, `time`, `pid`, `wl_socket` (`wayland-1`). It checks each lock file's pid, so dead directories are left out |
| `hyprctl -i <signature or index> …` | Talks to that instance whatever the environment says |
| `systemctl --user show-environment` | Has the live signature and `WAYLAND_DISPLAY=wayland-1` (uwsm updates it each start) |

So hyprctl already does the hard part, finding the live instances under this user's runtime
directory, and no socket probing of our own is needed. `WAYLAND_DISPLAY` stays `wayland-1` across
restarts, so `grim`, `wl-copy` and the input helper reconnect by themselves. Only the signature
goes stale.

## Design

### 1. One place: `host.ctl` re-resolves on a lost instance

`host.ctl` (`src/ai_mirror/host.py:12`) is the only path to `hyprctl` from MCP, the CLI and the
bar, apart from `index.sh`; see §4. When a call fails because the instance is gone:
- the error is `Couldn't connect to …`;
- or `HYPRLAND_INSTANCE_SIGNATURE was not set`.

In either case it calls `resolve()` once, then retries the call once. Any other failure is
raised as today. A dispatch is retried only if the first attempt failed to connect, so it never
ran.

`resolve()`:
1. Runs `hyprctl instances -j`. That needs no signature, and it scans only this user's
   `$XDG_RUNTIME_DIR/hypr/`.
2. Picks deterministically:
   1. the current `HYPRLAND_INSTANCE_SIGNATURE`, if it is listed (nothing to do);
   2. else the signature in `systemctl --user show-environment`, if listed. That names the
      session this user's services belong to, so it wins with nested or test instances;
   3. else the only listed instance, if there is exactly one;
   4. else it refuses (§3).
3. Sets `os.environ['HYPRLAND_INSTANCE_SIGNATURE']` to the pick, and also `WAYLAND_DISPLAY` from
   its `wl_socket` when that differs. The process environment is the cache: every later
   `hyprctl`, `grim`, `wl-copy`, `index.sh` and helper start inherits it. Nothing is re-resolved
   until the next lost-instance failure, so the idle path gains no polling.
4. Records the switch (old signature → new) in the audit log, as `instance-changed`.

### 2. A grant never crosses a compositor restart

**Proposed — user to confirm at spec review: revoke.**
- A grant is stamped with the instance it was given on. `_answer` adds
  `'instance': os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')` to `granted_state`, after a
  `host.ctl` call has made sure it's live; `_baseline_layers()` already makes one.
- `require_agent` revokes if the stamp no longer matches the current signature: owner off,
  generation bumped, a11y restored, `why` "Hyprland restarted since control was granted; ask
  again". That is the same path as the idle expiry.
- A pending request on the old instance is dropped the same way: its dialog died with the old
  shell.
- Why revoke: the human approved control of the session they were looking at. A new compositor
  is a new login as far as the screen goes. `wayland-1` names the new one too, so a helper
  started after the restart would type into it. Revoking costs one `control agent` click.
- `require_agent` compares against `os.environ`, which `resolve()` keeps current. Any observing
  call (`windows`, `screenshot` → `monitors`) that hits the dead instance updates it first.
  Input aimed at a dead instance fails in the helper as `unavailable` today, so no input reaches
  the new session under the old grant.
- A grant without an `instance` field (written before this change) is treated as matching, so
  updating doesn't revoke a live grant.

### 3. Errors and `doctor`

- No live instance: `MirrorError('unavailable', 'Hyprland is not running for this user
  (hyprctl instances is empty)')`.
- Several, none chosen by rule 2.1–2.2: `MirrorError('unavailable', 'N Hyprland instances are
  running (<signatures>); set HYPRLAND_INSTANCE_SIGNATURE to the one to drive')`.
- `doctor` (`api.py:133`):
  - It reports `compositor: reachable` after a resolve, plus `resolved: {from, to}`, so a stale
    start is visible rather than silently fixed.
  - When resolving fails, it reports `stale` (the inherited signature, which isn't running) next
    to today's `unset`, with the hint "Hyprland restarted after this process started; it now
    finds the running instance itself. If this persists, restart the MCP server".

### 4. `index.sh`

`index.py:51` runs `hyprctl` through its own `sh()`. It doesn't call `ctl`, to keep that module
read-only and guard-free. It gets the same retry: one shared `host.resolve()`, and a retry in
`sh()` only when `argv[0] == 'hyprctl'` and the failure is a lost instance. No other behaviour
changes.

### 5. nixarchy's shells

**Proposed — user to confirm at spec review: fix ai-mirror only; nixarchy is a separate issue if
wanted.** ai-mirror is where the failure hurt, and §1 fixes it for every parent process: herdr,
tmux or a systemd unit. A herdr pane would still give *other* Wayland tools the stale value.
That's nixarchy's to fix (refresh the variable from `systemctl --user show-environment` when a
pane shell starts), so it is out of scope here.

## Alternatives rejected

- **Probing sockets ourselves:** listing `$XDG_RUNTIME_DIR/hypr/` and connecting to each
  `.socket.sock`. `hyprctl instances` already does this, and checks pids, which is more than a
  connect test.
- **Always using the systemd user environment.** It's right on this host, but unset under
  plain `Hyprland` without uwsm, and in CI. It is rule 2.2, not the only rule.
- **Watching `$XDG_RUNTIME_DIR/hypr/` with inotify, or polling.** That adds a background thread
  to the idle path for an event a failed call already reports.
- **Telling the user to restart the MCP server.** That's today's state. Three attempts on p620
  to get it right show it isn't a fix.
- **Keeping the grant across a restart.** See §2: the human approved a session that no longer
  exists.
- **Passing `-i <signature>` on every `hyprctl` call instead of setting the environment.** It
  covers `hyprctl` but not `grim` or the helper, and changes every call site.

## Risks

- **Picking the wrong instance with several running** (nested Hyprland for tests, a second
  seat). Rule 2.1 keeps a valid inherited value, 2.2 prefers the user session, and otherwise it
  refuses. It never picks by time or guesses.
- **Mutating `os.environ` in a long-lived MCP server.** This is intended, since children must
  inherit it. Tests restore the environment, as the existing `patch.dict(os.environ, …)` tests
  do.
- **A Hyprland restart during the retry.** There's one resolve and one retry, then the error, so
  it can't loop.
- **The idle-expiry path and the instance check both revoking at once.** Both run under
  `locked('control')` and re-read the state, as the existing paths do.
- **Hosts:** every host that runs the MCP server. Nothing changes where the signature is
  already right (rule 2.1 returns before touching anything).

## Verification

- Unit tests (new `tests/test_instance_resolve.py`, existing style: `unittest`,
  `patch.object(host, …)`, `patch.dict(os.environ, …)`, a fake `subprocess.run`):
  - a stale signature: the first `hyprctl` fails "Couldn't connect", `instances` lists one, the
    retry succeeds, and `os.environ` holds the new signature;
  - unset → same;
  - several listed, the systemd one among them → that one; several, none matching → the
    `unavailable` message, with no environment change;
  - none listed → "not running";
  - a non-connect failure (`dispatch` returning an error) → raised, with no resolve and no
    retry;
  - a grant stamped with instance A, environment now B → `require_agent` raises `not_owner`
    with the restart message, and the generation is bumped;
  - a grant without a stamp → kept;
  - `doctor` after a resolve shows `resolved`; when resolving fails it shows `stale`.
- `python -m unittest discover -s tests` passes, and so does CI (#47).
- Live on p620: start the MCP server with the Oct 22 signature exported. `status` and
  `screenshot` work. `audit` shows `instance-changed`. A grant made before `omarchy-restart`
  (or a Hyprland restart) is revoked with the restart message, and `control agent` then works.
