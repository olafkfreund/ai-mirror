---
status: approved
issue: 39
intent: intent/2026-09-23-39-transient-baseline.md
---

# Spec: the baseline should mean "has been there all along"

## Design

One rule replaces the snapshot: **a namespace is exempt while it has been
mapped continuously since the grant.** It is enforced where the guard already
looks, so it costs nothing extra.

### The intersection

`_refuse_new_surfaces` (`control.py`) already calls `host.layers()` on every
window-addressed line. After that call and before judging, it narrows the
baseline to what is still mapped:

    still = {ns for ns in baseline if ns in mapped_namespaces}

Note `mapped_namespaces` is taken over **all levels**, not just level 2 and
above: `omarchy-background` sits at level 0 and must not be dropped for being
below the threshold the refusal uses.

If `still` is smaller than `baseline`, the difference is written back under the
control lock, and the departed names are remembered (below). The comparison
that follows uses `still`, so a surface that has gone is no longer exempt from
the moment it goes — not from the end of the grant.

The set can only shrink, so the change can only ever refuse more. That is the
property that makes it safe to apply inside a guard.

### Remembering what left

The state gains `baseline_departed`: namespaces that were in the baseline and
are not any more. It exists to answer the caller's obvious next question — is
this thing new, or is it something that was here, went, and came back? The
second is the more suspicious shape, and the refusal says so:

- not in the baseline and never was ->
  "`nixi (0x…)` opened since control was granted"
- in `baseline_departed` ->
  "`notification (0x…)` was mapped when control was granted, went away, and
  came back, so it is no longer treated as part of the desktop"

The list is capped at 32 namespaces, oldest dropped, because it is a message
aid and not a ledger.

### What is deliberately not done

The confirm dialog gets **no special case**. `omarchy-ai-mirror-confirm` is in
the baseline at the instant of the grant and gone immediately after, so the
first check removes it by the same rule as anything else. A namespace
allowlist would have to be maintained for every shell that ever draws a
dialog; this needs nothing.

**Answer to open question 1 (the bar restart):** accepted as-is, no
re-admission window. After `omarchy-restart-shell` the bar leaves the baseline
and returns as "departed and came back", so window-addressed input is refused
until control is re-taken. Re-admitting a namespace that returns within some
interval would reopen the hole for any surface that can be made to flicker, and
the cost of the strict rule is one keypress and a loud message rather than a
silent wrong destination. It is documented in the gotchas.

**Answer to open question 2:** yes, distinguish the two cases — see above.

## Alternatives rejected

- **Exclude ai-mirror's own confirm namespace by name.** Fixes the cosmetic
  half of #39 and leaves the real one: a notification up at the instant of the
  grant stays exempt for ten minutes.
- **Snapshot when the request is made rather than when it is answered.** The
  dialog is not up yet, so the cosmetic half goes — but a notification still
  might be, and the window between request and answer is under the person's
  control, not ours.
- **Record addresses instead of namespaces.** Distinguishes a returning
  surface from the original, which is most of what is wanted, but makes a bar
  restart indistinguishable from an impostor and offers nothing the
  intersection does not.
- **Re-baseline on a signal.** There is no signal. Hyprland's IPC has no event
  for "a layer took the keyboard" — that absence is the whole reason #29's
  guard is a heuristic.
- **Poll the layers in the background and maintain the set.** A daemon's worth
  of machinery to learn what the next call learns for free.

## Risks

- **razer, p620**: a bar or shell restart during a grant now refuses
  window-addressed input until control is re-taken. Expected, documented, and
  the message says which surface and why.
- **Write amplification**: the intersection writes state when it shrinks. A
  desktop that maps and unmaps a baseline namespace repeatedly could write on
  each cycle; it cannot loop, because each write only removes names and the set
  is finite for the life of the grant.
- **Lock contention**: the write takes the same `locked('control')` the rest of
  `control.py` uses, inside a per-line input path. It happens at most once per
  departed namespace per grant, so it is not in the hot path.
- **Interaction with #40**: a grant ended by another agent's server exit and
  re-taken starts a fresh baseline, so anything mapped at that moment becomes
  furniture again. This spec does not fix that; #40 does.

## Verification

- Unit: a baseline of three namespaces with one no longer mapped shrinks to
  two, the state is written once, and a later call with the same layers does
  not write again.
- Unit: a level-0 namespace still mapped is not dropped (the all-levels
  reading of `mapped_namespaces`).
- Unit: a namespace that left and returned produces the "went away and came
  back" message; one never in the baseline produces the "opened since" one.
- Unit: an absent baseline still skips the check; an unreadable `host.layers()`
  still returns without refusing.
- Unit: the departed list stays capped at 32.
- Live on razer, with control granted through the bar widget: the recorded
  baseline contains `omarchy-ai-mirror-confirm`; the first window-addressed
  call after the dialog closes removes it, leaving `omarchy-background` and
  `omarchy-bar`; opening nixi then refuses with the "opened since" wording.
