---
status: approved
issue: 30
spec: spec/2026-09-22-30-live-test-findings.md
---

# Plan: what ai-mirror says it did, and what it did

## Approved decisions, carried over

- **#30**: keep the per-line focus recheck (it is #24's guarantee). Change what
  a mid-batch refusal *says*: report the delivered prefix in lines and actions.
  "input was NOT sent" is used only when nothing was delivered.
- **#29**: Hyprland 0.56 exposes no keyboard-interactivity field (measured:
  `hyprctl -j layers` returns `address, alpha, h, namespace, pid, w, x, y`) and
  `activewindow` names the window under an overlay. So `_require_layer` drops
  its impossible `focused is None` precondition and keeps the rival check;
  `_require_focus` refuses while a surface mapped *after* the grant is up,
  against a baseline snapshotted by `set_owner`.
- **#31**: new code `wrong_target`, leaving `stale_generation` for ownership
  and generation changes.
- **#37**: document the middle button; do not chase it into the compositor.
- Fixes stay separable per issue: one commit per numbered step below.

## Steps

1. `src/ai_mirror/control.py`: `MirrorError.__init__` takes optional
   `details: dict | None`, stored as `self.details` → verify by unit test that
   `MirrorError('x', 'y', {'a': 1}).details == {'a': 1}` and that a two-arg
   call still works.
2. `src/ai_mirror/cli.py:99` and `src/ai_mirror/mcp.py:195`: merge
   `getattr(exc, 'details', None)` into the `{"error": {...}}` object →
   verify by calling a failing op through both surfaces and seeing the keys.
3. `src/ai_mirror/input.py:81` `encode()`: return `(lines, owners)` where
   `owners[i]` is the index of the action that emitted line `i`; update its
   callers → verify by unit test on a 3-action batch with a modifier, asserting
   the mapping covers every line.
4. `src/ai_mirror/control.py:458` `run_batch`: count acked lines; on a
   `_require_target` refusal raise `wrong_target` with details
   `{delivered, of, actions_completed, actions_total}` and the message
   "partial: N of M lines delivered (actions 1-k of j completed), then <reason>;
   the rest was not sent and held keys were released" — the old wording only
   when `delivered == 0` → verify by unit test with a fake helper failing on
   the nth line.
5. `src/ai_mirror/control.py` `_require_focus`: raise `wrong_target` instead of
   `stale_generation` → verify by unit test and by the existing
   `test_verified_input.py` suite still passing after its expectations are
   updated in the same commit.
6. `src/ai_mirror/control.py` `_require_layer`: delete the `focused is not None`
   refusal; keep the rival check; when a window still holds focus, put it in the
   result note ("window 0x... also holds focus, so if the surface does not take
   the keyboard these keys land in that window") → verify by unit test with
   fixtures from the razer nixi case, and live on razer.
7. `src/ai_mirror/control.py` `set_owner`: on a grant, record
   `baseline_layers` (namespaces mapped at that moment) and `baseline_at` in
   the control state; `_require_focus` refuses with `wrong_target` when a layer
   at level >= 2 whose namespace is not in the baseline is mapped, naming it →
   verify by unit test (baseline present/absent) and live with nixi open.
8. `src/ai_mirror/api.py:17` `doctor`: probe `host.focused_address()`; on
   failure return `ok: false` with `compositor` naming the missing variables
   and pointing at `demo/rz` → verify by running `doctor` over a bare ssh shell
   on razer (must now fail) and inside the session (must pass).
9. `src/ai_mirror/a11y.py:215`: compute `deep` from a node at level >=
   `CONTENT_DEPTH` that has a name, actions or text; extend `NO_CONTENT` for
   "deep nodes exist but none are actionable" → verify by unit test over a
   recorded GTK4 tree (false) and a recorded Chrome tree (true).
10. `src/ai_mirror/cli.py`: pass `by='agent'` for `control agent`; leave
    `confirm`/`deny` as `human` → verify by `ai-mirror control agent` on razer
    showing `"by": "agent"`.
11. `src/ai_mirror/cli.py`: accept `x,y,w,h` and `[x,y,w,h]` for `--region`,
    and name the expected form in the error → verify by both forms returning
    the same `region` in the result.
12. `src/ai_mirror/a11y.py:343`: split the `set_text` refusal into "needs text"
    and "no AT-SPI EditableText interface; use `focus` then `input`" → verify
    by unit test on a fake accessible for each cause.
13. `src/ai_mirror/gotchas.md`, `docs/usage.md`, `src/ai_mirror/mcp.py` tool
    descriptions: `wrong_target` vs `stale_generation`; the partial-delivery
    contract; typing into a surface while a window holds focus; the middle
    button being unavailable (#37); the session environment a non-login shell
    lacks → verify by `ai-mirror index` rendering the new gotchas.
14. Live check on razer with control granted: reproduce #30's cat-window case
    (error must name a partial delivery matching the file's contents); open
    nixi and type into the surface (must succeed) and at the window behind it
    (must refuse, naming nixi) → verify by the commands in Tests below.
15. Re-record `assets/demo-desktop.mp4` with `demo/demo.sh` as a whole-system
    check → verify by the video showing the same three acts with no errors.

## Tests

    # unit, as CI runs them
    cd /mnt/data/Source-home/GitHub/ai-mirror
    XDG_RUNTIME_DIR=$TMPDIR python3 -m unittest discover -s tests -v
    # expected: all pass, including the new tests/test_reporting_truth.py

    nix build .#checks.x86_64-linux.unittest -L
    # expected: builds clean

    # live, on razer (control must be granted by the person there)
    demo/rz control agent      # expected: "by": "agent"   (step 10)
    demo/rz doctor             # expected inside the session: ok true
    ssh razer ai-mirror doctor # expected: ok false, compositor named (step 8)

    # partial delivery (step 4)
    demo/rz launch alacritty --title "Bitwarden Vault" -e sh -c 'cat > /tmp/p.txt'
    demo/rz input --generation <g> --window <addr> \
      '[{"type":"type","text":"ABC"},{"type":"key","keys":["Return"]},{"type":"key","keys":["CTRL","d"]}]'
    # expected: either ok, or an error naming exactly what /tmp/p.txt contains

    # layer typing (steps 6, 7)
    demo/rz input --generation <g> --window <nixi layer addr> '[{"type":"type","text":"hello"}]'
    # expected: ok, note naming the focused window as the alternative destination
    demo/rz input --generation <g> --window <window addr> '[{"type":"type","text":"hello"}]'
    # expected: wrong_target, naming nixi as mapped since the grant

## Rollback

Every step is its own commit on `fix/30-live-test-findings`, so a single fix
can be dropped with `git revert <sha>` without touching the others. The whole
branch reverts cleanly: nothing changes on-disk state except the control state
file, which gains two keys (`baseline_layers`, `baseline_at`) that older code
ignores — a downgrade reads the file unchanged. No migration, no config.

The one behaviour change a rollback would matter for is step 7: if refusing
window-addressed input under new surfaces proves too strict in daily use,
reverting that commit alone restores today's behaviour while keeping the
truthful reporting from steps 1-6.
