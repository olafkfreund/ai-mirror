---
status: approved
issue: 54
spec: spec/2026-09-30-54-launch-reports-window.md
---

# Plan: launch says which window it opened

Branch `feat/54-launch-reports-window`, stacked on
`feat/53-verified-window-actions` (PR #55). **Implementation starts only
after #55 merges.** Then run `git rebase origin/master`, and re-check every
line reference below against the rebased files before editing. Line numbers
are as of `2eb9a23`.

## Approved decisions (self-contained)

- **Guard seam first.** `api._spawn(argv) -> int` holds the only `Popen` that
  `launch` uses. Its first line is `guard.check('api._spawn', 'api._spawn')`.
  Tests stub `api._spawn`. It lands as its own commit.
- **Flow**, after the existing argv validation:
  1. `timeout = wait._timeout(args.get('timeout'), default=5.0)`.
  2. `before = {r['address'] for r in host.windows()}`. If this raises, the
     error propagates and nothing is started.
  3. `pid = _spawn(argv)`.
  4. `wait.poll(check, timeout)`. `check(budget)` re-reads
     `host.windows(budget)` and holds when any row's address is not in
     `before`. It returns early on the first appearance. Any new window
     counts, whoever owns it.
- **After the spawn, `launch` never raises.** An error would invite a second
  launch.

  | poll result | extra fields beyond `ok: True`, `pid`, `waited_ms` |
  |---|---|
  | confirmed, 1 new row | `window` (address), `class`, `title` |
  | confirmed, >1 | `candidates: [{address, class, title}, …]` |
  | not_confirmed | `note: "no new window within {timeout:g}s; it may still appear -- call windows, do not launch again"` |
  | unavailable | `note: "started, but windows could not be read: {reason}. Call windows; do not launch again"` |

- **Arguments.**
  - MCP: `timeout` is a number, 0–30. Zero means one look.
  - CLI: `--timeout` (float), placed before `--`.
- **No argv rewriting.** `uwsm-app` is advice in `gotchas.md`, not a prefix
  ai-mirror adds.
- **Gotcha:** a new section, "What you launch dies with your terminal".
- **Docs:** `docs/usage.md` is updated.

## Steps

1. **`src/ai_mirror/api.py:9, 215-221`: the guard seam.**
   - Import `guard` (`from . import control, guard, host`).
   - Add a module-level function above `SESSION_VARS`:
     ```python
     def _spawn(argv: list[str]) -> int:
         """The one process launch starts. Guarded: tests stub this, never Popen."""
         guard.check('api._spawn', 'api._spawn')
         return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True).pid
     ```
   - In the `launch` branch: `return {'ok': True, 'pid': _spawn(argv)}`.
   - Add `tests/test_launch_window.py` with a single test: under `Base`
     (armed) with control granted, `api.run('launch', {'argv': ['true']},
     by='agent')` raises `guard.Blocked`.
   - → verify: `python3 -m unittest discover -s tests` is all OK, with one
     test more than before.
   - Name the new seam in AGENTS.md's "Tests cannot reach the desktop"
     invariant, next to `host.ctl dispatch`. *(Added during implementation:
     the plan missed that AGENTS.md lists the seams by name.)*
   - Commit alone: `test(guard): launch's Popen is a guarded seam (#54, plan step 1)`.
   - Traps:
     - `Blocked` is deliberately not a `RuntimeError`, so do not catch it.
     - The stdio and session arguments must be byte-identical: nothing may
       inherit the MCP stdout.
     - Do not touch `guard.py`.

2. **`src/ai_mirror/api.py` launch branch: before, spawn, after.**
   - Move the body into a module-level `_launch(args)`, next to `_window`,
     and import `wait` locally as `_window` does. Follow the flow and result
     table above exactly.
   - `class` and `title` come from the row (already trimmed to 240
     characters).
   - `waited_ms` comes from the poll result.
   - → verify: `python3 -m unittest discover -s tests` is all OK.
   - Traps:
     - `host.windows(budget)` takes the budget positionally or as
       `timeout=`, as #53 made it. Pass it through: one slow read must not
       blow the deadline.
     - The read before the spawn must happen *before* `_spawn`.
     - Nothing after `_spawn` may raise. Wrap only the poll's outcome
       mapping, not the spawn.
     - `wait.poll` already turns a failed read into `unavailable`, so do not
       add a second `try`.

3. **`src/ai_mirror/mcp.py:68-69` and `src/ai_mirror/cli.py:91-92`: the
   arguments.**
   - MCP schema: `'timeout': {'type': 'number', 'minimum': 0, 'maximum': 30}`.
   - MCP description, after the existing text: "Returns window (the new
     window's address, class, title) when exactly one appeared within
     timeout (default 5 s, 0 = look once), candidates when several did, a
     note when none did: never launch again because of a note. Launch
     desktop apps as ["uwsm-app", "--", …] so they outlive this server; see
     index gotchas."
   - CLI: `p.add_argument('--timeout', type=float)` before the `argv`
     REMAINDER argument.
   - → verify: `./bin/ai-mirror launch --help` shows `--timeout`, and
     `cli.build_parser().parse_args(['launch', '--timeout', '2', '--', 'foot'])`
     gives `timeout == 2.0` and argv `['--', 'foot']` (cli.py:135 strips the
     `--`).
   - Traps:
     - The MCP `number` type already rejects bool, nan and inf.
     - Do not change `cli.py:135`.

4. **`tests/test_launch_window.py`: the unit tests.** Stub `api._spawn`
   (count its calls, return pid 4242) and `host.windows` (a scripted
   sequence that accepts `timeout`). Cases:
   - One new window → `window`, `class`, `title`; one spawn.
   - Two new → `candidates` with two entries.
   - None within `timeout: 0.1` → `ok: True`, `note`, no `window`.
   - `windows` raising after the spawn → `ok: True`, `note` containing the
     reason, one spawn.
   - `windows` raising before the spawn → raises, zero spawns.
   - Bad argv → `ValueError`, zero spawns.
   - `host.windows` receives a timeout ≤ the requested timeout during the
     poll.
   - MCP `validate('launch', …)` accepts `timeout: 0`, and rejects `31` and
     `nan`.
   - The CLI parse from step 3.

   → verify: `python3 -m unittest tests.test_launch_window -v`.

   Traps:
   - Reuse `from test_invariants import Base, grant`, as
     `test_window_verified.py` does.
   - Never call `guard.disarm()`.
   - Use `timeout: 0.1` on the waiting paths so the suite stays fast.

5. **`src/ai_mirror/gotchas.md`: append a section** at the end, in the
   file's format (a heading, why it bites, then **Do:**):
   - **Heading:** `## What you launch dies with your terminal`
   - **Why it bites:** `launch` starts the program as a child of the MCP
     server, and the server lives in its terminal's systemd scope. On this
     host they were measured in a tmux scope and a foot scope. Closing that
     terminal kills everything the agent started.
   - **Do:** launch desktop apps as `["uwsm-app", "--", "<app>", …]`, or
     `["uwsm-app", "--", "gtk-launch", "<id>.desktop"]`, as Omarchy's
     `omarchy-launch-*` scripts do. `launch` does not add it for you.
   - *(Deviation: the planned "Also: a note…" line was dropped, and the
     section tightened, because the default index has a 20000-byte cap
     (`test_invariants`: "an index too large to read is an index nobody
     reads"), which the first draft broke at 20229. The `launch` tool
     description already says never to relaunch on a note.)*
   - → verify: `./bin/ai-mirror index --section gotchas | grep -A3 "dies with your terminal"`.
   - Traps: this file is hand-written and human-reviewed. Keep it factual,
     and cite only what was measured.

6. **`docs/usage.md:48, 92`: documentation.**
   - The `launch` row becomes `argv` (no shell), `timeout` 0–30 (default
     5), and the result: `pid`, plus `window`/`class`/`title`, or
     `candidates`, or `note` (never an error after the start).
   - The CLI line becomes
     `ai-mirror launch [--timeout S] -- uwsm-app -- firefox https://example.com`.
   - → verify: read it back.
   - Traps: none.

7. **Live check (manual; opens a real window).** With control granted:
   - `ai-mirror launch --timeout 5 -- uwsm-app -- foot --app-id aimirror-t54`
     returns `window` with class `aimirror-t54`.
   - Move it to an empty workspace with `ai-mirror window workspace <addr>
     --workspace 77`.
   - `cat /proc/<foot pid>/cgroup` shows its own `app-…scope`, not the
     terminal's. Find the pid with `hyprctl clients -j`, since `launch`'s
     `pid` is `uwsm-app`'s.
   - `ai-mirror launch --timeout 0 -- true` returns `note` immediately.
   - Close the window. `control off`.
   - → verify: outputs pasted into the PR.
   - Traps:
     - The new window opens on the human's active workspace until it is
       moved (seen in #53's live check). Move it at once.
     - Do not test `focus`: it switches the human's view.

## Tests

```sh
python3 -m unittest discover -s tests -v    # all OK; count = 197 (post-#53) + new
nix flake check
```

## Rollback

Revert the implementation commits. Keep step 1's guard even if the rest is
reverted: it only makes the tests safer. Nothing persists.
