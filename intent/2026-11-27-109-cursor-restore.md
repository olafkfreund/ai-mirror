---
status: draft
issue: 109
author: olafkfreund
---

# Intent: Preserve cursor settings when restoration fails

## Problem

PR #109 saves the desktop's cursor settings before showing the agent badge.
During release, GTK can refuse a theme or size write. The helper still reports
success and deletes the snapshot. The badge or its size can remain in desktop
apps, and the overlay has lost the settings it needs for another attempt.

## Proposed outcome

A failed or partially completed restore leaves the saved cursor settings
available for another attempt. The overlay can retry and restore both the
desktop theme and size once the write succeeds. A regression check demonstrates
the failed attempt and the successful retry.

## Affected users and systems

People using ai-mirror's cursor badge on Nixarchy, the cursor helper, and the
Omarchy overlay that calls it.

## Constraints

- Keep the saved settings until restoration succeeds or the user's newer
  cursor settings take precedence.
- Keep the existing idle-start behavior and respect newer cursor preferences.
- Preserve the existing control grant and kill-switch behavior.
- Exercise write failures in an isolated test.

## Open questions

None.
