---
status: approved
issue: 40
spec: spec/2026-09-23-40-grant-ownership.md
---

# Plan: a grant should belong to whoever was granted it

## Approved decisions, carried over

- A grant records `held_by`, the `{pid, start}` pair `register_server` already
  builds. `proc_start` is what makes it survive pid reuse.
- Three values, three meanings: a pair means a server holds it; `null` means a
  CLI caller holds it and no server may speak for it; **absent** means the
  grant predates this change and behaves as today, so an upgrade cannot leave a
  live grant unreleasable.
- Agent-initiated releases are checked; `by == 'human'` is never checked. The
  bar, `Super + Shift + Escape` and a terminal must always work.
- A holder that is not running does not hold anything: pid absent, or a
  different start time, means any agent may release. No waiting for the idle
  timeout.
- No takeover flag (open question 2). The audit names the holder (open
  question 3).

## Steps

1. `src/ai_mirror/control.py`: add module-level `SERVER = None`;
   `register_server` sets it to `{'pid': …, 'start': …}` and
   `unregister_server` clears it → verify by unit test that registering sets
   it and unregistering clears it.
2. `src/ai_mirror/control.py` `set_owner`: when `mode == 'agent'`, put `SERVER`
   into the request as `request['server']` → verify by unit test that a request
   made with a registered server carries it and one without carries `None`.
3. `src/ai_mirror/control.py` `_answer`: carry `request['server']` onto the
   granted state as `held_by` → verify by unit test on both shapes.
4. `src/ai_mirror/control.py`: add `_holder_running(held_by)` — `True` when
   `held_by` is a pair whose `proc_start(pid)` still equals its `start` → verify
   by unit test against this process (running) and against a pid that is not
   (gone), plus a mismatched start time.
5. `src/ai_mirror/control.py` `set_owner`: when `mode == 'off'` and
   `by == 'agent'`, refuse with `not_owner` unless `held_by` is absent, matches
   `SERVER`, or its holder is not running; `by == 'human'` is unaffected →
   verify by unit tests covering all four agent cases and the human case.
6. `src/ai_mirror/control.py`: add `release_if_held()` — releases only when the
   state's `held_by` matches `SERVER`, or when this server's own unanswered
   request is pending; silent otherwise → verify by unit test on a matching
   grant, a foreign grant, and a pending request.
7. `src/ai_mirror/mcp.py`: replace the `finally` block's `set_owner('off',
   'agent')` with `control.release_if_held()` → verify by unit test that a
   server shutdown leaves a foreign grant alone.
8. `src/ai_mirror/control.py`: `audit()` calls for grant, release, expiry and
   idle carry `holder` → verify by unit test reading the audit file.
9. `src/ai_mirror/gotchas.md`, `docs/usage.md`: a grant belongs to who took it;
   a server exiting no longer ends another agent's grant; `not_owner` can now
   mean "held by another agent" and what to do about it → verify by
   `ai-mirror index` rendering the new text.
10. Live on razer: take control through the CLI, start an MCP server on the
    host and stop it, and confirm the grant survives → verify by the commands
    in Tests.

## Tests

    # unit, as CI runs them
    cd /mnt/data/Source-home/GitHub/ai-mirror
    XDG_RUNTIME_DIR=$TMPDIR python3 -m unittest discover -s tests -v
    # expected: all pass, with the new cases in tests/test_grant_ownership.py

    nix flake check
    # expected: all checks passed

    # live, on razer (control granted by the person there)
    demo/rz control agent          # answer on the desktop
    demo/rz status                 # expected: held_by is null (a CLI grant)
    ssh razer 'ai-mirror mcp < /dev/null'   # a server that starts and exits
    demo/rz status                 # expected: owner still agent -- the bug, fixed
    demo/rz control off            # by human; always allowed

## Rollback

One commit per step. Steps 5, 6 and 7 are the behaviour and revert together;
steps 1-4 and 8 are recording and are harmless alone. The state file gains one
optional key that older code ignores, and a grant carrying `held_by` is
released by an older build exactly as it is today, so a downgrade loses the
protection without stranding anything.

If the check proves too strict in practice — a fleet where servers legitimately
clean up after each other — reverting step 5 alone restores unrestricted agent
releases while keeping the shutdown fix in step 7, which is the narrower half
of the problem.
