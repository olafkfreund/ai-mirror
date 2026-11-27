---
status: draft
issue: 109
intent: intent/2026-11-27-109-cursor-restore.md
---

# Spec: Keep the cursor snapshot until GTK restoration succeeds

## Design

Use the existing retry path in PR #109. The overlay retries a nonzero
cursor-helper exit and the helper removes its runtime snapshot only after
the restore calls return successfully.

- In `src/ai_mirror/cursor.py`, keep the GTK fallback conditional on GTK
  still showing the agent badge. Use the restore target already selected
  by `sync`, including its precedence for newer desktop preferences.
- Restore the GTK size first when it differs from the target. Check the
  return value from `set_int`. Then restore the theme and check
  `set_string`. If either required write returns false, raise an error
  that names the failed setting. The helper exits nonzero and the
  snapshot remains available for the existing overlay retry.
- A failed theme write leaves the badge visible to the next attempt.
  If the size write already succeeded, that attempt can skip it and
  restore the theme. Call `settings.sync()` after the required writes
  succeed. Successful restores and newer GTK themes follow the current
  snapshot cleanup path. Idle startup and the control gate keep their
  existing behavior.

## Alternatives rejected

- Checking return values while writing the theme first leaves a retry
  gap. If the theme succeeds and the size fails, the badge check skips
  the size on the next attempt.
- Adding state to record which GTK writes are pending would change the
  snapshot format. Writing the theme last lets the existing snapshot
  and overlay retry handle both failure cases.

## Risks

- A permanently unwritable setting keeps restoration pending, with the
  existing overlay retry interval. The saved preferences remain
  available.
- The GTK fallback relies on the backend reporting write failures. This
  change covers rejected writes and retries after partial completion.

## Verification

- Extend `tests/test_cursor.py` with an isolated GTK settings stub.
  Refuse a size write while the badge is present and verify the theme
  setter is never reached and the snapshot survives. Refuse a theme
  write after a successful size write and verify the snapshot survives
  and the badge remains. In both cases, allow writes on the next
  attempt and verify that the saved theme and size are restored and the
  snapshot is removed.
- Run the existing idle, native-theme, newer-preference and restore
  retry cases, the full Python suite, and `nix flake check`.
