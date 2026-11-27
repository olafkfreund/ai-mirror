---
status: draft
issue: 104
intent: intent/2026-11-27-104-change-aware-capture.md
---

# Spec: Change-aware window screenshots

## Design

Add an opt-in comparison to the MCP `screenshot` tool. Pass
`compare: true`, a `window` address and the current `generation`. The
result includes the usual full window frame and metadata, plus a
`comparison` object. This mode requires `image: true` (the default) and
uses the normal 1280-pixel default. A caller can request a smaller image
within the existing range. Ordinary screenshots and the CLI keep their
current interface. MCP owns the baseline because each CLI invocation is
a separate process.

- Require the active, unexpired grant held by this MCP server. Check the
  holder and generation before capture and again before publishing a
  frame or updating the baseline. Use the same holder test as the event
  recorder. The comparison reads grant state without refreshing the
  inactivity timer.
- Reuse the window identity, privacy check, geometry and view-only
  calculation in `control.screenshot`. Capture the selected window with
  `grim -T`, using stdout and the same PNG settings for each request.
  Before publishing, verify the window still has the same stable ID,
  geometry and visibility classification, and repeat its privacy check.
  If any check fails, discard the in-flight image. A resize between two
  successful requests establishes a fresh baseline. A resize during one
  request requires a fresh capture.
- Cap the requested scale, actual image dimensions and encoded size.
  Stop and reap the capture when it exceeds five seconds or 8 MiB of
  PNG output. Use a bounded read of stdout so the byte limit applies
  during capture. Return an error on invalid PNG headers, oversized
  output or capture failure. Keep the image in memory through response
  assembly. Use the same image for comparison and the returned frame.
- Keep one baseline per server. Store only its SHA-256 digest, the
  generation, capture identity and geometry, and the returned frame ID.
  Compare only with the immediately preceding successful comparison
  capture. Match the stable ID and address, output, logical rectangle,
  scale, actual image dimensions and visibility classification. Clear
  the baseline on the existing release signal, on a failed grant check,
  and on server exit. A generation change makes the previous baseline
  ineligible immediately. Ordinary screenshots do not update it.
- Return `comparison.status` as `baseline`, `unchanged` or `changed`.
  The `baseline` response gives a reason, such as no prior capture,
  another target or different geometry. The other responses give
  `comparison.previous_frame`. Each successful response replaces the
  baseline. Hidden and covered captures keep the existing view-only rule.
- Report what was observed in the two PNG frames. Equal digests mean
  the same captured image data. Different digests mean the image data
  differs. Keep the encoding settings stable and document that this
  comparison can include cursor-like UI effects such as a caret blink.
  The existing `input.confirm` predicate remains the way to verify a
  specific state transition.

## Alternatives rejected

- Hyprmasq's compositor plugin and offscreen input bring exact Hyprland
  build coupling and a separate input-authorization model. ai-mirror
  already has window capture and input confirmation.
- Changed crops and animation suppression require additional image
  processing. Establish the usefulness of a whole-frame signal first.
- Short clips add continuous sampling and cleanup. A concrete case
  with an action that cannot be verified from two frames will determine
  whether they are needed.

## Risks

- A window can redraw while its geometry stays fixed. The comparison is
  evidence about the two captures. Changes between them may be missed.
- A caret, clock or animation can produce a change unrelated to the
  action under test. The fresh frame lets the agent inspect the cause.
- Unexpected output size, a compositor restart, or a grant change can
  interrupt the comparison. The tool reports the error and the agent
  must observe again before acting.

## Verification

- Exercise the public MCP call with a deterministic same-window
  fixture. Capture twice with the same image, toggle a visible status
  label, then capture again. Expect `baseline`, `unchanged`, `changed`,
  with the expected full PNG and frame metadata in each response.
- Cover a wrong or expired grant, a second MCP server, revocation during
  capture, privacy refusal before and after the capture, target
  replacement, resize, scale mismatch, hidden and covered windows,
  invalid or oversized PNG, timeout, and cleanup after failure.
- Run the existing screenshot, frame mapping, ownership and input
  confirmation regressions, then the full Python suite and
  `nix flake check`. Verify the status-label workflow with a live test
  session when an approved plan reaches implementation.
