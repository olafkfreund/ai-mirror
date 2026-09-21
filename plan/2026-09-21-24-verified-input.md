---
status: draft
issue: 24
spec: spec/2026-09-21-24-verified-input.md
---

# Plan: A keystroke should not land in a window nobody chose

## The approved decisions, carried over

`input` types into whatever holds focus when the keystroke arrives. `generation`
(`control.py:233`) answers "do I still have permission"; `frame` (`mcp.py:125`)
answers "are these coordinates from a current view". Neither answers "is the
window I meant still in front", and keyboard actions carry no coordinates so
`frame` cannot help them at all.

1. **`input` gains an optional `window`** — a Hyprland address of the kind
   `windows` returns. **Required when the batch contains keyboard actions**,
   refused otherwise. Breaking, and deliberately so: the alternative is a default
   that is silently unsafe.
2. **The check lives in `run_batch`'s existing per-line loop** (`control.py:378`),
   beside the ownership recheck. A batch is not atomic; that loop already exists
   because the desktop moves underneath one.
3. **The caller names the window; we never pin current focus.** Pinning would not
   have fixed the reported incident — the shell restarted and another panel took
   the agent's place *before* its next action, so a batch starting then would
   have pinned the wrong window and proceeded.
4. **The comparison is positive**: `focused == named` proceeds, everything else
   refuses. `{}`, `None`, a raised error, a malformed reply and a different
   address all take the same branch, so no behaviour of Hyprland's needs to be
   known in advance. This is #51's shape, inverted.
5. **Pointer actions are unchanged.** `frame` already binds them, and a focus
   check would refuse the ordinary case of clicking an unfocused window in order
   to focus it.
6. **Editor detection and the conversational-text heuristic are out of scope**,
   deferred to their own issue on their own evidence.

## Steps

1. **`host.py`**: add `focused_address() -> str | None` using
   `ctl('activewindow', '-j')`. Returns the address, or `None` when the reply
   carries none. It does **not** catch `ctl`'s `RuntimeError` — a failed query
   must reach the caller as a failure, not as `None`, because step 3's comparison
   treats `None` and "different" alike but the *message* differs.
   → verify by a unit test with `ctl` stubbed for: a normal reply, `{}`, and a
   raised `RuntimeError`.

2. **`input.py`**: add `needs_window(actions) -> bool`, true when any action's
   `type` is in `{'type', 'key', 'key_down', 'key_up'}`.
   **Decided from the actions, never from the encoded lines.** `encode` emits
   `K <mod> 1` for modifiers wrapped around *pointer* actions (`input.py:74`), so
   sniffing wire prefixes would demand a window for a ctrl+click.
   → verify by a unit test asserting a modifier-laden click is **not** keyboard.

3. **`control.py:378` `run_batch`**: take `window: str | None = None`. Inside the
   existing loop, before each line, when `window` is set:

   ```python
   if host.focused_address() != window:   # positive match; see decision 4
       helper.cancel()
       raise MirrorError('stale_generation', ...)
   ```

   Written as `!=` against a named address this is still the positive form —
   there is exactly one value that proceeds. The refusal distinguishes "focus is
   a different window" from "focus could not be read" for the model's benefit,
   *after* the decision to refuse, never as part of it.
   → verify by unit tests: mismatch sends no helper line; focus changing
   mid-batch aborts the remainder.

4. **`api.py:96`**: pass `window` through to `run_batch`, and refuse a keyboard
   batch that has none — `MirrorError` with the remedy in it ("call `windows`,
   pick the address, pass it as `window`"), since a model that is only told "no"
   retries.
   → verify by a unit test on the refusal and its message.

5. **`mcp.py:59`**: add `window` to the `input` schema and say in the description
   that it is required for typing and why. Keep it one sentence — that tool
   description is already dense.
   → verify by `validate('input', ...)` accepting and rejecting the right shapes.

6. **The success message stops overstating.** Delivery to a named window is all
   that has been established: not that the application accepted the input, and
   not that the task completed.
   → verify by the unit test asserting the returned text.

7. **Tests** on `Base` (`tests/test_invariants.py:55`), like every other class
   here — not bare `TestCase`, which is how #19's class lost `guard.arm()` and
   its isolated `XDG_RUNTIME_DIR`.
   The mismatch test asserts **no helper line was sent**, on the helper stub
   rather than on the returned message: a guard that refuses after typing would
   pass a message-level assertion while the keystroke had already landed.
   → verify by the full suite green.

8. `nix flake check`.
   → verify by `all checks passed!`.

## Tests

```
python -m pytest tests -q      # or the repo's runner; expect green
nix flake check                # expect "all checks passed!"
```

## Rollback

`git revert` the implementation commit. `window` is additive to the wire
protocol and nothing persists it, so a revert restores today's behaviour exactly
— including, deliberately, today's unsafe default.
