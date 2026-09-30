---
status: approved
issue: 54
intent: intent/2026-09-30-54-launch-reports-window.md
---

# Spec: launch says which window it opened

Builds on #53. `wait.poll(check, timeout)` and `wait._timeout(value,
default)` are from #53's plan step 1 (commit 236c9ee on
`feat/53-verified-window-actions`). This branch is rebased onto `master`
after #53 merges, and implementation starts only then.

## Design

### 1. Guard the seam first

In `src/ai_mirror/api.py`, move the `Popen` call from the `launch` branch
(`api.py:150-156`) into a module-level `_spawn(argv) -> int`. It calls
`guard.check('api._spawn', 'api._spawn')` and then the unchanged `Popen`
(argv, all three stdio streams on `DEVNULL`, `start_new_session=True`,
`close_fds=True`), and returns the pid.

This follows AGENTS.md: the check goes on the innermost real call, the one a
test stubs. The same shape is used for `host.ctl` and `Helper.cmd`. It lands
as its own commit, before anything else changes.

### 2. Before, spawn, after

In the `launch` branch, after the existing argv validation:

1. `timeout = wait._timeout(args.get('timeout'), default=5.0)`.
2. `before = {w['address'] for w in host.windows()}`. If this read fails, the
   exception propagates and **nothing is started**. "Could not look" before
   the launch is the one moment an error costs nothing.
3. `pid = _spawn(argv)`.
4. `wait.poll(check, timeout)`. `check` re-reads `host.windows()`, keeps the
   rows whose `address` is not in `before`, and holds as soon as there is at
   least one (intent Q1: return early). Any new window counts, whoever owns
   it (intent Q2).

### 3. Result

After step 3, `launch` never raises. The process is already running, and an
error invites the agent to launch it again: two windows, two editors on one
file. Every outcome is `ok: true`:

| poll result | fields beyond `ok`, `pid`, `waited_ms` |
|---|---|
| confirmed, one new row | `window`: its address, plus `class` and `title` |
| confirmed, several | `candidates`: `[{address, class, title}, …]` |
| not_confirmed | `note`: "no new window within Ns; it may still appear, so call windows. Do not launch again." |
| unavailable | `note`: "started, but windows could not be read: <reason>. Call windows. Do not launch again." |

`class` and `title` go through `host.windows()`'s existing 240-character
trim. They are untrusted text (#49); this change adds no new trust in them.

### 4. Arguments

- **MCP** (`mcp.py`, the `launch` tool): add
  `timeout: number, minimum 0, maximum 30`. Zero is honoured as one look,
  which is what a caller starting a program with no window wants.
  - The description gains: "Returns window (the new window's address) when
    exactly one appeared within timeout (default 5 s), candidates when
    several did. Launch desktop apps as ["uwsm-app", "--", …] so they
    outlive this server; see index gotchas."
- **CLI** (`cli.py`, the `launch` parser): `--timeout` (float). It has to come
  before `--`, because argv is `REMAINDER`.

### 5. Gotcha

A new section in `src/ai_mirror/gotchas.md`, "What you launch lives in your
terminal's scope":

- **Measured:** the MCP servers on this host sit in a tmux scope and a foot
  scope, so closing that terminal kills everything the agent launched.
- **Do:** launch desktop apps as `["uwsm-app", "--", "<app>", …]` or
  `["uwsm-app", "--", "gtk-launch", "<id>.desktop"]`, as Omarchy's own
  `omarchy-launch-*` do. `launch` does not add it for you.

The section is hand-written, as that file requires. It is proposed in this
diff and reviewed like any other.

### 6. Docs

In `docs/usage.md`: update the `launch` row and the CLI line, and list the
new result fields.

## Alternatives rejected

- **Prefixing `uwsm-app` automatically.** It rewrites what the agent asked
  to run, breaks non-desktop commands, and hides the reason. The intent
  rules it out.
- **Attributing windows by pid.** It fails for launchers and single-instance
  apps, and pids are shared across windows (#53). Decided in the intent.
- **Waiting for the full timeout to collect every new window.** Every
  successful launch would then cost 5 s. The early return (intent Q1) keeps
  the usual case fast.
- **Raising `not_confirmed` like #53's `window`.** A failed window action is
  safe to observe and retry. A launch reported as failed gets launched
  twice. So the answers deliberately differ.
- **Hyprland's `openwindow` event.** For the same reasons as `wait.py`: it
  needs a socket listener, and the state read is 10 ms.

## Risks

- **A window the human opens during the wait is attributed to the agent.**
  It is reported as `window` if it is the only new one. The window is short
  (usually under 1 s) and the mistake is visible in `class`/`title`, which
  the result includes so the agent can check.
- **Splash screens.** The early return reports the splash, and the main
  window comes later. `class` usually still matches. Covered by the
  `candidates`/`note` wording that says to call `windows`.
- **`launch` is now slow when nothing opens:** 5 s for a program with no
  window. Callers pass `timeout: 0`.
- **Adding the guard can break a test that reached real `Popen` through
  `launch`.** None exists today (checked: only `tests/smoke.py`, which is
  not in the unit suite). If one appears, it was a bug.

## Verification

- Unit tests (`tests/test_launch_window.py`, `guard` armed, `api._spawn` and
  `host.windows` stubbed):
  - One new window → `window` with class and title.
  - Two new windows → `candidates`.
  - None within `timeout: 0.1` → `note`, `ok: true`.
  - `windows` failing after spawn → `note` with the reason, `ok: true`, one
    spawn.
  - `windows` failing before spawn → raises, zero spawns.
  - Bad argv → `ValueError`, zero spawns (unchanged).
  - With `_spawn` **not** stubbed, `launch` raises `guard.Blocked` (the new
    seam test).
  - The MCP schema accepts `timeout: 0` and rejects 31 and `nan`.
- `index --section gotchas` shows the new section.
- `python3 -m unittest discover -s tests -v` and `nix flake check` are
  green.
- Live: `ai-mirror launch --timeout 5 -- uwsm-app -- foot` returns `window`,
  and `hyprctl clients` shows that address with class `foot`. Then check the
  new process's `/proc/<pid>/cgroup` is its own `app-…scope`.
