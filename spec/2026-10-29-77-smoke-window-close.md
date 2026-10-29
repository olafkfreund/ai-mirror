---
status: draft
issue: 77
intent: intent/2026-10-29-77-smoke-window-close.md
---

# Spec: check_wait leaves no window behind

## Design

One change, in `tests/smoke.py` `check_wait`, inside its discovery loop (the
`for p in candidates:` loop, ~line 160):

1. Before each press, next to the existing layer snapshot, record the window
   addresses: `wins = {w['address'] for w in host.windows()}`.
2. In the loop's existing `finally:`, after `hide(p['id'])`, close every window
   whose address isn't in `wins`:
   `api.run('window', {'generation': gen, 'action': 'close', 'address': a})`.

Why this is enough:
- **Timing:** a key that opens a window opens no layer, so the loop already waits
  its full 5 s before the `finally`. The window has mapped by then.
- **Only new windows:** the set difference against that press's own snapshot
  means a window that was already open is never touched (intent constraint).
- **The same rules apply:** the close goes through `api.run('window', …)`, the
  path `smoke.py` already uses at ~line 69, so control, generation and the
  confirm-after-dispatch check (`'close': r is None`) apply.
- **Errors stay loud:** a close that isn't confirmed raises, and the smoke run
  fails. It doesn't carry on with a stray window focused.

Part 2 of the issue (the layer pick, `sorted(new)[0]`) is left out, as approved
in the intent. The issue gets a comment saying so, and is closed with the PR.

## Alternatives rejected

- **Skip candidates whose `opens_with` command isn't a `shell toggle`:**
  `index.plugins()` gives the key, not what the key runs, so this needs a new
  lookup. Cleaning up after the fact is shorter and covers any cause.
- **Close via `hyprctl dispatch closewindow`:** this bypasses ai-mirror's own
  control check and confirmation. The smoke run should use the API it tests.
- **Snapshot windows once before the loop:** a window the user opens during the
  run would then be closed. A per-press snapshot keeps the window short.

## Risks

- **Over-closing:** a window the user opens during the 5 s after a press is
  closed. That's the same exposure the existing layer diff accepts. The smoke
  run is driven by hand with control granted, so the user isn't typing then.
- **`host.windows()` failing:** it raises, as `host.layers()` already would, and
  the run fails loudly. p620 only.

## Verification

- `python -m pytest tests/ -q` passes (the smoke file is unchanged except
  this loop; CI's `check` stays green).
- **A forced live case on p620** (with control granted):
  - run `check_wait` once with a temporary candidate whose key opens a window
    (a monkeypatched `index.plugins()` returning the terminal key's binding as
    `opens_with`), shown in the PR;
  - after the run, the window set equals the set before it.
- **The normal live run:** `python tests/smoke.py` (`check_wait`) still passes
  on p620.
