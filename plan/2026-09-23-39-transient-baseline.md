---
status: approved
issue: 39
spec: spec/2026-09-23-39-transient-baseline.md
---

# Plan: the baseline should mean "has been there all along"

## Approved decisions, carried over

- A namespace is exempt while it has been **mapped continuously since the
  grant**. Enforced by intersecting `baseline_layers` with what is mapped, in
  `_refuse_new_surfaces`, which already lists the surfaces.
- The intersection reads mapped namespaces at **all levels**, not just
  `KEYBOARD_LEVEL` and above: `omarchy-background` sits at level 0 and must not
  be dropped for being below the refusal's own threshold.
- The set can only shrink, so the change can only refuse more.
- State gains `baseline_departed`, capped at 32, so a returning surface reads
  differently from a new one.
- No special case for `omarchy-ai-mirror-confirm`; the general rule removes it
  on the first check after the grant.
- A restarted shell is treated as new until control is re-taken. No
  re-admission window (open question 1). Documented in the gotchas.
- Absent baseline still skips the check; an unreadable `host.layers()` still
  returns without refusing.

## Steps

1. `src/ai_mirror/control.py`: add `DEPARTED_CAP = 32` and `_forget_departed(
   state, gone)` — a helper that appends the gone namespaces to
   `baseline_departed`, de-duplicated, oldest dropped past the cap → verify by
   unit test on the helper alone, including the cap.
2. `src/ai_mirror/control.py` `_refuse_new_surfaces`: after `host.layers()`,
   compute `mapped = {ns for every layer at any level}` and
   `still = [ns for ns in baseline if ns in mapped]`; when `still != baseline`,
   take `locked('control')`, re-read the state, write back `baseline_layers =
   still` plus the updated `baseline_departed` → verify by unit test that a
   departed namespace is removed, the state is written once, and a second call
   with the same layers does not write again.
3. `src/ai_mirror/control.py` `_refuse_new_surfaces`: judge against `still`
   rather than `baseline`, and build the message in two parts — namespaces in
   `baseline_departed` get "was mapped when control was granted, went away, and
   came back, so it is no longer treated as part of the desktop"; the rest get
   the existing "opened since control was granted" → verify by unit test on
   both wordings.
4. `src/ai_mirror/gotchas.md` and `docs/usage.md`: say that the exemption is
   continuous presence, that a restarted bar therefore refuses until control is
   re-taken, and what the two refusal wordings mean → verify by `ai-mirror
   index` rendering the new text.
5. Live on razer with control granted through the bar widget: confirm the
   recorded baseline contains `omarchy-ai-mirror-confirm`, that the first
   window-addressed call after the dialog closes removes it leaving
   `omarchy-background` and `omarchy-bar`, and that opening nixi then refuses
   with the "opened since" wording → verify by the commands in Tests.

## Tests

    # unit, as CI runs them
    cd /mnt/data/Source-home/GitHub/ai-mirror
    XDG_RUNTIME_DIR=$TMPDIR python3 -m unittest discover -s tests -v
    # expected: all pass, with the new cases in tests/test_reporting_truth.py

    nix flake check
    # expected: all checks passed

    # live, on razer (control granted by the person there, through the widget)
    demo/rz status   # expected: baseline_layers includes omarchy-ai-mirror-confirm
    demo/rz launch gnome-text-editor /tmp/aim-39.txt
    demo/rz input --generation <g> --window <addr> '[{"type":"type","text":"x"}]'
    demo/rz status   # expected: baseline_layers is now background + bar only
    # open nixi (SUPER+H), then:
    demo/rz input --generation <g> --window <addr> '[{"type":"type","text":"x"}]'
    # expected: wrong_target, "nixi (0x…) opened since control was granted"

## Rollback

One commit per step, so any can be reverted alone; steps 2 and 3 are the
behaviour and revert together cleanly. The state file gains one optional key
(`baseline_departed`) that older code ignores, and `baseline_layers` shrinking
is invisible to a downgrade: an older build reads whatever set is there and
applies the snapshot rule to it. No migration.

If the strict restart rule proves too irritating in daily use, reverting step 3
alone keeps the intersection and drops the two-wording message; reverting step
2 as well restores today's snapshot behaviour.
