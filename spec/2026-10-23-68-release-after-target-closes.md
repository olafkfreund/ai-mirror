---
status: draft
issue: 68
intent: intent/2026-10-23-68-release-after-target-closes.md
---

# Spec: a key-up after its target closes does not fail the batch

## Design

One rule for windows and layers: **a matched release may go out after its
target refused, only if the target is gone.** Everything else in `run_batch`
is today's code.

### 1. The normal path is unchanged

`run_batch` (`src/ai_mirror/control.py`) keeps calling `_require_target(window)`
before every line, ownership and generation are still re-read first, and every
failure path still calls `helper.cancel()` (which sends `C`). PR #52's
`target_validated` / `target_owner` / `target_is_layer` skip is removed: it let
any release after a validated layer through without a check, matched or not.

### 2. Track what this action pressed

A set `pressed` holds the press lines sent for the current action, keyed by
their prefix (`'K 27'`, `'B 272'`). A line `K <code> 1` / `B <code> 1` adds its
prefix after the helper acks it; the set is cleared whenever the line's owner
(from `owners`) differs from the previous line's. With `owners` absent there
is no action boundary, so nothing is ever exempt.

### 3. The rescue, only on refusal

When `_require_target(window)` raises `MirrorError` and the line is a release
(`K <code> 0` / `B <code> 0`) whose prefix is in `pressed`:

```python
def _target_gone(window: str) -> bool:
    """True only when the target demonstrably no longer exists. Raises if
    either list cannot be read: "could not ask" is not "gone"."""
    if any(l['address'] == window for l in host.layers()):
        return False
    return not any(w['address'] == window for w in host.windows())
```

- `True` → send the release, set `closed = True`, carry on.
- `False` (the target exists but lost focus) → re-raise the original refusal,
  exactly as today.
- Any exception → re-raise the original refusal (fail closed).

`_require_target` itself is not reused for "gone": it turns a failed layer
query into "no layers" (`control.py:724-727`), and for a window it only knows
what has focus (`_require_focus`), which cannot tell a closed window from one
that lost focus.

### 4. A true result note

`run_batch`'s success note (`control.py:814-828`) today says "`<window>`,
which still had focus" or "the topmost surface on screen". When `closed` is
set it says instead: "delivered to `<window>`, which closed after the
keystroke; its key-up was still sent. Application acceptance and task
completion are NOT verified -- observe before reporting the outcome." The
result gains `closed: true`.

### 5. Tests (`tests/test_layer_typing.py`, with `host` stubbed)

1. A window that closes on Enter-down: `['K 28 1', 'K 28 0']`, the window in
   `host.windows()` on the first check and gone on the second → both lines
   sent, `closed: true`, note says it closed.
2. A layer that closes on Escape-down → both sent (#52's existing test,
   unchanged expectation).
3. The target still exists but another window took focus → the release is
   refused, `wrong_target`, as today.
4. An unmatched release (`K 28 0` with no `K 28 1` earlier in the action) →
   refused when the target is gone.
5. `host.windows()` raising during the gone check → the original refusal, not
   a send.
6. A release matched in a *previous* action is not exempt in the next one.

## Alternatives rejected

- **Broad rule: send any matched release wherever focus is.** Covers a
  shortcut whose key-down opens something, but the intent decided narrow:
  a release only skips the check when there is nowhere it could land wrongly.
- **#52 as it is (layers only, unmatched).** Misses windows and exempts
  releases it never pressed.
- **Treat "focus moved" as "gone".** A window closing on a workspace with
  another window moves focus there; so does the human clicking elsewhere.
  Only the window list can tell them apart.

## Risks

- **An extra `hyprctl clients` and `layers` call**, only on the refusal path
  of a matched release -- never on the normal path.
- **Address reuse:** if Hyprland reused the closed window's address for a new
  window within milliseconds, the target would look present and the release
  would be refused as today -- fail closed.
- **A shortcut that opens something** still reports a partial failure, as
  today (intent's recorded trade-off).

## Verification

- `python3 -m unittest discover -s tests` green, with the six tests above.
- `nix flake check` green.
- Live, after #67 is merged into this branch: `tests/smoke.py` `main()` passes
  end to end under a grant.
