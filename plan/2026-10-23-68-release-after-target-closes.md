---
status: draft
issue: 68
spec: spec/2026-10-23-68-release-after-target-closes.md
---

# Plan: a key-up after its target closes does not fail the batch

Self-contained. Branch `fix/layer-release-input` (PR #52, which becomes #68's
implementation; `master` merged in at `31eb954`). Line numbers as of
`3f6e6e5`; re-find by the quoted text if they drift.

## Approved decisions (from the spec)

1. **Normal path unchanged.** `_require_target(window)` before every line;
   owner + generation re-read first; every failure calls `helper.cancel()`
   (sends `C`) then raises `_partial(...)`. #52's `target_validated` /
   `target_owner` / `target_is_layer` skip is **removed**.
2. **`pressed`**: the set of `'K <code>'` / `'B <code>'` prefixes pressed and
   not yet released in the current action. Add after the helper acks a
   `… 1` line; remove after it acks a `… 0` line; clear when a line's owner
   differs from the previous line's. `owners is None` → never exempt.
3. **Rescue**, only inside the existing `except MirrorError` around
   `_require_target`, only when `exc.code == 'wrong_target'`, the line is a
   release `K <code> 0` / `B <code> 0`, its prefix is in `pressed`, and
   `_target_gone(window)` returns `True`. Then send the line and set
   `closed = True`. Otherwise `helper.cancel(); raise _partial(exc, ...)` as
   today. `_target_gone` raising → treated as not gone (original refusal).
4. **`_target_gone(window)`**: `False` if any `host.layers()` entry has that
   address; else `not any(w['address'] == window for w in host.windows())`.
   Errors propagate to the caller (which refuses).
5. **Note**: when `closed`, the success note reads "keys pressed in
   `<window>`, which then closed; the matching key-up was sent after it
   closed, to whatever has focus now. Application acceptance and task
   completion are NOT verified -- observe before reporting the outcome." and
   the result gains `closed: True`.
6. A rescued key-up goes to the new focus, the same place `C` sends it on the
   failure path today: an accepted limitation, stated in the note.

## Steps

1. **`src/ai_mirror/control.py`: `_target_gone`.** Add after `_require_target`
   (ends ~line 733), with a docstring saying "could not ask" is not "gone":
   ```python
   def _target_gone(window: str) -> bool:
       if any(layer['address'] == window for layer in host.layers()):
           return False
       return not any(w['address'] == window for w in host.windows())
   ```
   → verify by `python3 -m unittest discover -s tests` (still green; unused yet).
   Traps: do NOT wrap the reads in try/except here; the caller decides.

2. **`src/ai_mirror/control.py` `run_batch` (lines ~775-812): the rescue.**
   Replace the `target_validated` / `target_owner` / `target_is_layer`
   variables and the `releasing` / `same_action` / `if not (...)` block with:
   ```python
   pressed, action, closed = set(), None, False
   ...
       owner = owners[delivered] if owners and delivered < len(owners) else None
       if owner != action:
           pressed, action = set(), owner
       if window is not None:
           try:
               surface = _require_target(window)
           except MirrorError as exc:
               head, _, edge = line.rpartition(' ')
               rescued = False
               if (exc.code == 'wrong_target' and owners is not None and edge == '0'
                       and line[:2] in ('K ', 'B ') and head in pressed):
                   try:
                       rescued = _target_gone(window)
                   except (RuntimeError, ValueError, OSError, KeyError, TypeError,
                           subprocess.SubprocessError):
                       rescued = False
               if not rescued:
                   helper.cancel()
                   raise _partial(exc, delivered, lines, owners) from None
               closed = True
   ```
   After a successful `OK` ack (just before `delivered += 1`):
   ```python
   if line[:2] in ('K ', 'B '):
       head, _, edge = line.rpartition(' ')
       (pressed.add if edge == '1' else pressed.discard)(head)
   ```
   Keep the ownership check (`read_state()`) as the first thing in the loop,
   untouched. → verify by the unittest command.
   Traps: AGENTS.md "run_batch re-reads the state before every helper line and
   sends C on every failure path" -- the rescue must not move or skip either.
   `surface` keeps its value from the last successful check when rescued.

3. **`src/ai_mirror/control.py`: the note (lines ~814-828).** In the
   `if window is not None:` block, when `closed` is true set `result['closed']
   = True` and use the closed wording from decision 5 instead of the
   `surface` / "still had focus" wording. → verify by the unittest command.

4. **`tests/test_layer_typing.py`: tests.** Patch `host.layers`,
   `host.windows` and `host.focused_address` in every test (unstubbed reads
   reach the live compositor or fail in `nix flake check`). Use
   `FakeHelper` (from `test_invariants`, records `sent`, acks from a list) and
   `self.granted` from `TypingIntoASurface.setUp`; pass `owners=`.
   - Update `test_key_release_is_sent_when_surface_closes_on_keydown`: add
     `patch.object(host, 'windows', return_value=[])`; expectation unchanged.
   - New, in a class `ReleaseAfterTargetCloses(TypingIntoASurface)`:
     1. window closes on Enter-down (`['K 28 1','K 28 0']`, owners `[0,0]`,
        focus `WINDOW` then `'0xother'`, `host.windows` without `WINDOW`)
        → both sent, `result['closed'] is True`, note contains "then closed".
     2. target still in `host.windows()`, focus moved → `wrong_target`, only
        `'K 28 1'` and `'C'` sent.
     3. unmatched release (`['K 28 0']`, target gone) → refused.
     4. `host.windows` raising during the gone check → refused, `C` sent.
     5. `host.layers` raising during the gone check → refused.
     6. matched in a previous action (`['K 28 1','K 28 0','K 28 0']`, owners
        `[0,0,1]`, gone before line 3) → line 3 refused.
     7. repeated code in one action (`['K 30 1','K 30 0','K 30 0']`, owners
        `[0,0,0]`, gone after line 2) → line 3 refused.
     8. revoked before the would-be rescued up (`set_owner('off','human')`
        from `on_cmd` after `'K 28 1'`) → `stale_generation`, `C` sent.
     9. rescued up acked `'ERR'` (`FakeHelper(acks=['OK','ERR'])`) →
        `unavailable`, `C` sent.
     10. `owners=None` → refused.
     11. modifier: `['K 29 1','K 46 1','K 46 0','K 29 0']`, owners `[0]*4`,
         gone after line 2 → all four sent; with owners `[0,0,0,1]` → line 4
         refused.
     12. `unavailable` refusal (`host.focused_address` raising on the up) with
         the target gone → refused, not rescued.
   → verify by the unittest command; every new test must fail on `master`'s
   `run_batch` where it asserts a send (check by temporarily reverting
   step 2 locally, not committed).
   Traps: `FakeHelper.cmd` raises when an ack in its list is an Exception;
   `typed(helper)` strips `'C'`.

5. **Merge PR #67 into this branch once #67 is merged to `master`**, resolving
   `tests/test_layer_typing.py::test_windows_op_lists_both`, where #67 adds
   `'generation'` to the expected keys. Then live, under a grant from the
   confirm dialog: `nix develop -c python3 -c "import sys; sys.path.insert(0,'tests'); import smoke; smoke.main()"`
   passes. → verify by its `PASS:` line.
   Traps: smoke's `check_index` needs #66; `check_wait` needs a panel this host
   no longer has -- run `main()` only.

## Execution

Steps 1-4 edit one source file and one test file across four steps, so they go
to one `coder` agent, step by step, each verified by `codex review
--uncommitted` (no custom prompt -- it is rejected) and agy (read-only, single
commands), then committed naming the step. A fresh Opus review checks
`git diff master...HEAD` against this plan. Step 5 is the session model's.

## Tests

```sh
python3 -m unittest discover -s tests -v   # green, 12 new + 1 updated
nix flake check                             # green
```

## Rollback

Revert the step commits; the branch returns to PR #52's original layer-only
rule. No state, config or plugin changes.
