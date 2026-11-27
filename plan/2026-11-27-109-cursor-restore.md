---
status: draft
issue: 109
spec: spec/2026-11-27-109-cursor-restore.md
coders:
  1: "codex (manager) — handle the two GTK writes in the existing restore helper"
  2: "codex (manager) — exercise both rejection paths with the existing isolated cursor fixture"
reviewers:
  - "agy (plan) — check write ordering, the retry contract, and test coverage"
  - "agy (diff) — independently verify the helper and regression tests against the approved plan"
---

# Plan: Preserve the cursor snapshot when a GTK write fails

PR #109 uses a per-compositor runtime snapshot to restore the desktop
cursor after the agent badge. Its overlay already retries a nonzero
helper exit. Keep GTK restoration conditional on GTK still showing the
badge. A rejected write must reach the existing retry path with the
snapshot retained.

## Steps

1. In `src/ai_mirror/cursor.py:50`, keep the existing badge check and
   desktop-write guard in `restore_gtk`. Compare the current
   `cursor-size` with the restore target. If they differ, write the
   target size and raise `RuntimeError` naming `cursor-size` when
   `set_int` returns false. Then write `cursor-theme` and raise
   `RuntimeError` naming that key when `set_string` returns false.
   Call `settings.sync()` after the required writes succeed. Writing
   the theme last keeps the badge check true for the next attempt after
   either failure. Leave `sync` at `:67`, the on-disk snapshot, and the
   overlay unchanged. Its current call order propagates an error before
   unlinking the snapshot. A newer GTK theme takes precedence, and an
   idle shell start with no snapshot leaves the cursor alone.
   Verify with `python3 -m unittest tests.test_cursor -v`.

2. In `tests/test_cursor.py:67`, add regression coverage through
   `cursor.sync`. Use the temporary runtime directory and a fake
   compositor that switches back to a native cursor while GTK retains
   the badge. Keep `guard.arm()` and stub the write guard only for
   the test's fake settings. Model the getters and successful setters
   using the same in-memory GTK state.
   - Refuse the size write. Assert the error names `cursor-size`, the
     theme was untouched and the snapshot still exists. Allow a retry
     and assert both the saved theme and size are restored and the
     snapshot is gone.
   - Refuse the theme write after accepting the size. Assert the error
     names `cursor-theme`, the badge and snapshot remain, and the
     restored size is already set. Allow a retry. Assert it skips the
     already-correct size, restores the theme, and removes the
     snapshot.
   Verify both cases and the existing idle, theme-change, native-theme
   and IPC-retry tests with `python3 -m unittest tests.test_cursor -v`.

## Tests

- `python3 -m unittest tests.test_cursor -v` passes, including both
  rejected-write tests and their successful retries.
- `python3 -m unittest discover -s tests -v` and `nix flake check` pass
  on the final PR tree. The tests use fake compositor and GTK writes.
- Required GitHub CI passes before merging PR #109.

## Rollback

Revert the implementation commit. The runtime snapshot format and
overlay protocol stay compatible.
