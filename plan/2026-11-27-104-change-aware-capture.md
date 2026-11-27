---
status: approved
issue: 104
spec: spec/2026-11-27-104-change-aware-capture.md
---

# Plan: Change-aware window screenshots

Add an opt-in mode to the MCP `screenshot` tool. The caller passes
`compare: true`, a window address and its current generation. It receives
the usual full window image and frame metadata plus a comparison with the
preceding successful comparison in this MCP server. The first release
compares whole PNGs. Ordinary screenshots, CLI capture, and
`input.confirm` retain their existing behavior.

## Steps

1. Share the window capture preparation in `src/ai_mirror/control.py:959`.
   Extract the window lookup, stable ID validation, privacy refusal,
   monitor lookup, logical geometry and hidden or covered classification
   from `screenshot`. Reuse them in both paths. Add a stdout capture
   entry point for comparison that takes an explicit window and
   `max_size`. Use `grim -T` with the same PNG settings for all comparison
   calls, with a 1280-pixel longest edge by default and the option to
   request 320–1280 pixels. Keep the established view-only metadata.
   Reinspect the same window after reading stdout and require the same
   stable ID, address, monitor, rectangle and visibility classification.
   Apply the same privacy check on both inspections. Propagate a privacy
   refusal or fail the capture if its target or geometry changed.
   Verify with `python3 -m unittest tests.test_window_capture -v` and the
   post-capture cases from step 4.

2. Bound the new capture at the subprocess boundary in
   `src/ai_mirror/control.py:1016`. Send PNG to stdout. Read from the pipe
   in bounded chunks with a monotonic five-second deadline and an 8 MiB
   total limit. Detect overflow with a one-byte lookahead. Kill and reap
   unfinished children and close their pipes on every failure. Keep
   stderr and stdin away from MCP stdout. Validate the PNG signature,
   IHDR and nonzero dimensions within the requested longest-edge limit.
   Return a capture error for bad headers, nonzero exit, timeout or
   oversized output. Keep PNG bytes in memory through response assembly.
   Put the test guard at the subprocess seam. Verify with the bounded
   reader tests in step 4.

3. Wire the opt-in mode in `src/ai_mirror/mcp.py:55`, `:120` and `:278`.
   Validate a nonempty window, integer generation and image mode.
   Reject `image: false`, monitor and region arguments with comparison.
   Validate grant ownership before capture and again before accepting the
   result. Reuse the predicate at `src/ai_mirror/events.py:53`, compare
   the generation, and reject an expired grant using the inactivity
   limit. Read state without invoking the `require_agent` path that
   refreshes idle time. A failed grant check clears the baseline. A
   generation change immediately disqualifies the old baseline. Extend
   the existing SIGUSR1 release handler to clear comparison state while
   still aborting the helper. Clear comparison state on server exit.
   Share normal frame registration and message assembly so the PNG that
   was compared is the PNG that is returned. Keep one baseline containing
   the SHA-256 digest, frame ID, generation, window stable ID and address,
   monitor, rectangle, scale, actual dimensions and visibility
   classification. An absent baseline or mismatched generation, target,
   geometry or scale establishes a new baseline and returns
   `comparison: {status: "baseline", reason: ...}`. A match returns
   `comparison: {status: "unchanged" | "changed", previous_frame: ...}`
   according to digest equality. Every successful comparison replaces the
   baseline. Ordinary screenshots leave it alone and view-only frames
   still fail through `from_frame`. Verify through the public MCP tool
   in step 4.

4. Add `tests/test_capture_comparison.py`, using the guard in
   `src/ai_mirror/guard.py:30` and the existing window fixture in
   `tests/test_window_capture.py:20`. Stub compositor reads and exercise
   the public MCP call. Check one baseline, one identical full PNG and
   one changed PNG from a visible status-label fixture. Check target
   replacement, geometry and scale changes between captures, changes
   during a capture, and hidden and covered frames. Cover privacy
   refusals before and after capture, absent, expired and stale grants,
   another server, a CLI-owned grant, and revocation while capturing.
   Verify that a refused capture does not publish a frame, that release
   and grant failures clear the baseline, and that ordinary screenshots
   do not change it. Exercise invalid headers and dimensions,
   oversized stdout, timeout, process failure and cleanup using a
   synthetic subprocess or a stub of the innermost spawn. Keep the
   tests isolated from the desktop. Verify with
   `python3 -m unittest tests.test_capture_comparison -v`.

5. Document the MCP arguments and the JSON result in `docs/usage.md:53`
   and the frame guidance near `:103`. Describe the five-second and
   8 MiB capture limits, default and allowed image sizes, grant rules,
   replacement of the baseline, and view-only handling. Explain that a
   difference is a change in captured PNG data. Carets, clocks and
   animations can change the result. Use the existing `input.confirm`
   predicate when an action needs to verify a specific state change.
   Two requested frames can miss intermediate changes. Verify the
   documentation against the public MCP response tests.

## Tests

- `python3 -m unittest tests.test_capture_comparison tests.test_window_capture tests.test_grant_ownership tests.test_generation_required tests.test_input_confirm -v`
  should pass the comparison, window geometry, control and confirmation regressions.
- `python3 -m unittest discover -s tests -v` and `nix flake check`
  should pass the full repository checks.
- In an approved live test session, open a deterministic window with a
  togglable status label. Capture it twice before toggling the label,
  then capture again. Expect `baseline`, `unchanged` and `changed` in sequence,
  with matching full images and frame metadata. Resize and recapture
  for a new baseline. Revoke control and verify the comparison is
  refused. Use the ai-mirror skill and the normal human grant for this
  check. Follow the skill's session selection before driving a desktop.

## Rollback

Revert the implementation commits. Comparison stores one digest and
metadata in process memory. Restarting the MCP server discards them.
