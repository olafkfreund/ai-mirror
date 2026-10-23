---
status: approved
issue: 65
spec: spec/2026-10-23-65-background-a11y-act.md
---

# Plan: a11y_act can be trusted to act without taking the human's cursor

Self-contained. Branch `fix/65-background-a11y-act`. Line numbers are as of
`867a09e`; re-find by the quoted text if they drift.

## Approved decisions (from the spec)

1. **Measure before changing `click`.** Per application on this machine:
   action names offered, and whether `click`, a named action, `set_text`,
   `focus` move the pointer, change the active window, or change keyboard
   focus. Recorded as measured examples per application, not a toolkit rule.
2. **`click`** matches `('click', 'press', 'activate', 'jump')` plus the
   default-click names the measurement found (expected `doDefault`). No match
   → `unsupported: element actions are [...]`. No index-0 fallback.
   `do_action` returning `False` → `unavailable`.
3. **One guarded seam** `a11y._write(seam, call)`; all three AT-SPI writes go
   through it. `except guard.Blocked: raise` before `act()`'s
   `except Exception`. `_write` is never called inside a `wait.poll` probe.
4. **Read-back.** `set_text`: full text compared, `verified: true` or
   `not_confirmed` with ≤120 chars + length in `details`. `focus`: `focused`
   state, `verified: true` or `not_confirmed`. Named actions/`click`:
   `verified: null` + note. Poll ≤1 s (`timeout` overridable), re-resolve each
   probe, compare role; gone or different role → `states_after: null`
   (`not_confirmed` for `set_text`/`focus`, reported for named actions).
5. **Generation required** on `a11y_act`, `window`, `launch`, and clipboard
   `write` by an agent. Human CLI clipboard write stays ungated. `windows`,
   `a11y_tree`, `a11y_find` return `generation` read **before** the walk.
   CLI: `--generation` required on `a11y-act`, `window`, `launch`; `--expect`
   (JSON) and `--timeout` on `a11y-act`.
6. **Words.** `a11y_act` description: `focus` takes keyboard focus; others
   do not move the pointer; which activate a window is in `index`/gotchas.

## Steps

1. **Measure (session model, live; no code).**
   Ask the human for control. On an empty workspace on a monitor they are not
   using, launch one window each of the installed apps among GTK3, GTK4, Qt,
   Firefox, Chromium (`--force-renderer-accessibility --user-data-dir=<scratch>
   --no-first-run`). Focus a *different* window, then for each app run
   `ai-mirror a11y-find` for a button, a checkbox, an entry and a link and
   record their `actions`; then for `click`, one named action, `set_text`
   and `focus` record before/after `hyprctl cursorpos`,
   `hyprctl activewindow -j | jq .address` and the focused node
   (`ai-mirror a11y-tree --app <name>` filtered with
   `jq '[.nodes[] | select((.states // []) | index("focused"))]'` --
   `a11y-find` has no state filter). `control off` after.
   Output: a table in the PR description and the default-click names for
   step 3. → verify by: the table has a row per app × action.
   Traps: `omarchy-toggle-notification-silencing` first; the measurement runs
   *current* code, so `click` may still use the index-0 fallback -- record
   which action name actually ran.

   **Result (2026-10-23, Hyprland on this host, target window not focused,
   the human's terminal focused throughout).** Installed: GTK4
   (gnome-calculator), Firefox, Chrome. Not installed: GTK3, Qt.

   | App | Element | Actions offered | Action | Result | Active window changed | Pointer moved |
   |---|---|---|---|---|---|---|
   | GTK4 calculator | button `7` | `click` | click | ok | no | no |
   | GTK4 calculator | text entry | `text.*`, `clipboard.*`, `menu.popup` (no click) | set_text | ok | no | no |
   | GTK4 calculator | button `7` | `click` | focus | `atspi_error` (grab_focus unsupported) | no | no |
   | Chrome | button | `press`, `showContextMenu` | click | ok; in-page focus moved to it | no | no |
   | Chrome | check box | `check`, `showContextMenu` | click | ok **only via the index-0 fallback** | no | no |
   | Chrome | entry | `activate`, `showContextMenu` | set_text | `unsupported` (no EditableText) | no | no |
   | Chrome | entry | `activate`, `showContextMenu` | focus | ok; in-page focus moved to it | no | no |
   | Chrome | link | `jump`, `showContextMenu` | click | ok | no | no |
   | Chrome | label text | `doDefault`, `showContextMenu` | -- | (a name match on "Your name" hit the label, not the entry: target entries by role) | | |
   | Firefox | button | `press` | click | ok | no | no |
   | Firefox | check box | `check` | click | ok **only via the index-0 fallback** | no | no |
   | Firefox | entry | `activate` | set_text | ok (EditableText present) | no | no |
   | Firefox | entry | `activate` | focus | ok | no | no |
   | Firefox | link | `jump` | click | ok | no | no |

   Findings:
   - No action, in any app, changed the active window or the workspace. Every
     "pointer moved" seen during the runs coincided with the human using the
     mouse and did not reproduce on rerun; AT-SPI has no call that moves it.
   - **Check boxes in Chrome and Firefox offer `check`, not a click name.**
     Removing the fallback without adding it breaks clicking them.
     `DEFAULT_CLICKS = ('doDefault', 'check', 'uncheck')` -- `doDefault` seen on
     Chrome text, `uncheck` the unmeasured counterpart a checked box offers.
   - **Firefox exposes no content while its window is on a hidden workspace**
     (application and frame only); on a visible one, full tree. Chrome exposes
     content hidden. GTK4 calculator too.
   - `focus` changes in-page focus in the browsers without activating the
     window; on GTK4 `grab_focus` fails outright.
   - A fresh Firefox profile opens a "make default" dialog first; dismissing
     it with `a11y-act <Not now> click` worked.

2. **`src/ai_mirror/a11y.py`: the guarded seam.**
   Add after `_call` (~line 116):
   ```python
   def _write(seam: str, call):
       """The one place a11y changes an application. Tests stub this."""
       guard.check(f'a11y.act {seam}', 'a11y._write')
       return call()
   ```
   In `act()` (lines 355-393) wrap `comp.grab_focus()`,
   `editable.set_text_contents(text)` and `iface.do_action(index)` as
   `_write('grab_focus', comp.grab_focus)` etc., keeping their boolean checks.
   Add `except guard.Blocked: raise` immediately before
   `except Exception as exc:  # GLib.Error` (line 391).
   Tests (`tests/test_reporting_truth.py`, next to the existing `_act`
   helper at line 290, which uses `Base` semantics via `guard`): with the guard
   armed and `resolve` patched to a fake accessible offering `['click']`,
   `act('1.0.0', 'click')` raises `guard.Blocked`, not `MirrorError`; same for
   `focus` and `set_text`.
   → verify by `python3 -m unittest discover -s tests -v`.
   Traps: the guard goes on the innermost call a test stubs (AGENTS.md);
   reads stay unguarded; check the test class arms the guard (`Base.setUp`
   does; a plain `TestCase` does not -- arm it explicitly if needed).
   - Deviation: the test class `SetText` is a plain `unittest.TestCase`, so the new test calls `guard.arm()` itself, as the trap allowed.
   - Deviation: one test covers `click`, `focus` and `set_text` with a `MagicMock` accessible, instead of three separate tests.
   - Deviation: `guard.arm()` is never disarmed afterwards, so the guard stays armed for later plain `TestCase`s in the same process.

3. **`a11y.py:384-388`: click semantics and refusal.**
   `wanted = ('click', 'press', 'activate', 'jump', *DEFAULT_CLICKS)` for
   `click`, where `DEFAULT_CLICKS` is a module constant holding the names from
   step 1: `('doDefault', 'check', 'uncheck')`, with a one-line comment
   citing #65. `index = next((names.index(w) for w in wanted
   if w in names), None)`. After `_write('do_action', ...)` returns falsy:
   `raise MirrorError('unavailable', f'the application refused {names[index]}')`.
   Tests: `['showContextMenu']` + `click` → `unsupported` and `_write` not
   called; `['doDefault']` + `click` → `do_action(0)`; `do_action` → `False`
   raises `unavailable`. Stub `a11y._write` to record calls.
   → verify by the unittest command.
   Traps: `iface` may be `None` → `names == []` → `unsupported` (keep that).
   - Deviation: the three new tests are in a new class `ClickSemantics` in `tests/test_reporting_truth.py`, not in an existing one.

4. **`a11y.py` `act()`: read back.**
   Signature `act(node_id, action, text=None, expect=None, timeout=None)`.
   Before acting: `role = _call(acc.get_role_name, '')`,
   `states_before = _node(acc, node_id, Atspi).get('states', [])`.
   After the write, outside any `try` that could swallow `Blocked`:
   ```python
   from . import wait
   after = None
   def probe(budget):
       nonlocal after
       try:
           node, _ = resolve(node_id)
       except MirrorError as exc:
           if exc.code != 'stale_node':
               raise
           node = None
       after = node if node is not None and _call(node.get_role_name, '') == role else None
       if action == 'set_text':
           return after is not None and _full_text(after) == text
       if action == 'focus':
           return after is not None and 'focused' in _node(after, node_id, Atspi).get('states', [])
       return True
   result = wait.poll(probe, wait._timeout(timeout, default=1.0))
   ```
   `_full_text(acc)`: Text iface `get_text(0, -1)` via `_call`; returns
   `None` when the node has no Text interface or the read fails, and `probe`
   treats `None` as not confirmed (never equal, not even to `''`), so an
   unreadable field cannot verify an empty write. Keep the last read in a
   `got` variable (`None` if the node went away); mismatch `details` are
   `{'text': got[:120], 'length': len(got)}` when `got` is a string, else
   `{'text': None, 'length': None, 'reason': 'node gone or text unreadable'}`.
   `result['result'] == 'unavailable'` → `MirrorError('unavailable', reason)`.
   `not_confirmed` for `set_text` → `details={'text': got[:120], 'length':
   len(got)}`; for `focus` → `details={'states_after': ...}`.
   Return `{'ok': True, 'node', 'action', 'verified': True | None,
   'states_before', 'states_after' (list or None), 'waited_ms'}`; named
   actions add `'note': 'invoked; the effect is not visible to accessibility
   -- observe before reporting it'`.
   `api.py:275` passes `args.get('timeout')`.
   Tests: `set_text` read-back mismatch → `not_confirmed` with ≤120 chars;
   match → `verified: True`; probe resolving to a different role →
   `states_after: None`; `click` → `verified: None` with note. Patch
   `a11y.resolve`, `a11y._write`, and `wait.time` or use `timeout=0.1`.
   → verify by the unittest command.
   Traps: `wait.poll` catches every exception (`wait.py:164`), so no `_write`
   inside `probe`; `MirrorError` has `.code` (check `control.py`).
   - Deviation: The read-back lives in a new helper `_read_back()`, called from `act()`, plus `_full_text()` and `_states()`, instead of inline in `act()`. The behaviour is the plan's.
   - Deviation: `states_before` and `states_after` use `_states()`, which wraps `_node` in `_call` and defaults to `[]`, so the pre-read does not raise on minimal fake accessibles such as `FakeAccessible`.
   - Deviation: Existing `ClickSemantics._run` changed `get_action_name.side_effect` from a list to a lambda indexing names; the new pre-read via `_node` also calls `get_action_name` and exhausted the list.
   - Deviation: Added a `ReadBack` test class with 4 tests (set_text mismatch truncated to 120 chars with length, set_text match verified, different role gives `states_after: None`, click gives `verified: None` with note). No focus read-back test.
   - Deviation: Not changed: CLI and MCP `--timeout`/`--expect` and the timeout schema (steps 5 and 7). `api.py` now passes `args.get('timeout')` to `act`, as step 4 says.

5. **Generation: `api.py`, `mcp.py`, `cli.py`.**
   - `api.py:161` `_generation`: message
     `'generation is required -- from status, windows, a11y_find, a11y_tree or a screenshot frame'`.
   - `api.py:255`: `generation = _generation(args)` for every op in
     `MUTATING` (drop the `if op != 'input'` default).
   - `api.py:224`: `control.require_agent(_generation(args))`.
   - `api.py` `windows` (~line 214), `a11y_tree` (235), `a11y_find` (238):
     read `gen = control.read_state().get('generation')` first, return
     `{**result, 'generation': gen}`.
   - `mcp.py:63-79`: add `'generation': INT` to `window`, `launch`,
     `a11y_act` properties and to their required lists; `clipboard` gets it
     optional; `a11y_act` gets `'timeout': {'type': 'number', 'minimum': 0.1,
     'maximum': 30}`. Add one sentence to `INSTRUCTIONS` (line 83): window,
     launch, a11y_act and clipboard write take the generation from status,
     windows, a11y_find/a11y_tree or a screenshot.
   - `cli.py`: `--generation type=int required=True` on `window` (line 85),
     `launch` (94), `a11y-act` (109); on `a11y-act` also
     `--expect type=json.loads` and `--timeout type=float`.
   - Update existing tests: `tests/test_launch_window.py:18,45` (pass the
     grant's generation), `:97-101` `test_mcp_timeout_schema` (add
     `'generation': 1` to every `validate('launch', ...)` call so the timeout
     is what fails), `:103-105` `test_cli_parse` (add `--generation 1` before
     `--`); `tests/test_window_verified.py:50,169,173` and its CLI parse test
     near 176 (add `--generation 1`); `tests/test_invariants.py:348` (pass the
     grant's generation) and `:352` (pass that same, now-revoked generation so
     it still fails with `not_owner`, not `ValueError`);
     `tests/test_layer_typing.py:59` (expected keys become
     `{'windows', 'layers', 'generation'}`).
   - New tests: each of the four without generation → `ValueError` naming
     the sources; with a stale one → `stale_generation`; `windows`,
     `a11y_tree`, `a11y_find` carry `generation` read before the walk (stub
     `host.windows`/`a11y._walk` to bump the state mid-call; result keeps the
     old value).
   → verify by the unittest command.
   Traps: generation + owner gate all mutating ops (AGENTS.md); the a11y
   import in `api.py` stays local (keeps gi off the import path); MCP tool
   errors stay `isError` results, never a dead server.

6. **Callers outside the unit tests.**
   - `tests/smoke.py`: `gen` from line 38 into `launch` (42), `window` (44),
     agent clipboard write (56); in `finally`, use `state['generation']` from
     line 67 for the `window close` at 69.
   - `demo/demo.sh`: `--generation $G` on every `launch`, `window` and
     `a11y-act` line (26, 34, 44, 51-53, 69, 75, 79, 82 and any others
     `grep -n 'launch\|window \|a11y-act' demo/demo.sh` finds).
   → verify by `bash -n demo/demo.sh` and
   `grep -n 'launch\|window \|a11y-act' demo/demo.sh` showing `--generation`
   on each.
   Traps: `launch` takes argv via `REMAINDER`, so `--generation` must come
   before the program.

7. **Words.**
   - `mcp.py:78` `a11y_act` description: add "focus takes keyboard focus;
     set_text and named actions never move the pointer; see index gotchas for
     which ones activate their window. Pass generation."
   - `src/ai_mirror/gotchas.md`, section "Accessibility trees are
     per-application, and mostly absent": the step 1 table, framed as measured
     examples.
   - `docs/usage.md:56-58,100-102`: `generation` on the four operations,
     `--expect`, `--timeout`, the new result fields.
   → verify by the unittest command (tests that pin doc/instruction text).
   Traps: `gotchas.md` is read-only data the index serves; hand-written only.

8. **Verify everything.** Commands under Tests. Then live, under a grant:
   `tests/smoke.py`, and one `a11y-act` click and `set_text` against a GTK
   window showing `verified` and `states_after`.

9. **Release note.** The PR description gets a "Breaking change" section:
   `window`, `launch`, `a11y_act`/`a11y-act` and agent clipboard writes now
   require `generation`; where to get one; `click` no longer falls back to an
   element's first action. The repo has no CHANGELOG and releases are
   version-bump commits, so the next release PR copies this section.
   → verify by: the section is in the PR body.

## Execution

Step 1 is the session model's (it needs the human's grant). Steps 2-7 go to
one `coder` agent, started with this plan and step 2, each later step sent by
`SendMessage`. After each step: `codex review --uncommitted` (read-only) and
an agy read-only review, then commit naming the step. Final review: a fresh
Opus agent given only this plan and `git diff master...`. Step 8 is the
session model's.

## Tests

```sh
python3 -m unittest discover -s tests -v   # all green, new tests included
node --test tests/*.mjs                     # unchanged, green
nix flake check                             # green
AI_MIRROR_HELPER=$(nix build .#ai-mirror-input --print-out-paths)/bin/ai-mirror-input python3 tests/smoke.py   # live, moves the mouse
```

## Rollback

Each step is its own commit; `git revert` the range on the branch, or close
the PR unmerged. No state file, config or plugin format changes, so nothing
to migrate back. External scripts broken by the required generation recover
by reverting the release.
