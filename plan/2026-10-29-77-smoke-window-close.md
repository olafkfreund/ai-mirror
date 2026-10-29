---
status: approved
issue: 77
spec: spec/2026-10-29-77-smoke-window-close.md
---

# Plan: check_wait leaves no window behind (#77)

Decisions carried from the approved spec:

- **One change:** `tests/smoke.py` `check_wait`'s discovery loop.
  - Snapshot window addresses before each press.
  - After `hide(p['id'])`, close each new window through
    `api.run('window', {'generation': gen, 'action': 'close', 'address': a})`.
- **Only windows new since that press's own snapshot** are closed, never one
  that was open before.
- **A close that fails raises,** and the smoke run fails.
- **The layer pick (`sorted(new)[0]`) is left out.** Say so on the issue and close it
  with the PR.

Below three file-editing steps, so the lead implements it (no coder handoff).

Worktree: `/mnt/code/Source-home/GitHub/ai-mirror-77`, branch
`fix/77-smoke-window-close`.

## Steps

1. **`tests/smoke.py:162-174` (the `for p in candidates:` loop).**
   - At line 163, next to `before = {l['namespace'] for l in host.layers()}`, add
     `wins = {w['address'] for w in host.windows()}`.
   - In the `finally:` at 173, after `hide(p['id'])`, add:
     ```python
     # A key that opened a window instead of a panel: close it, or the
     # next press lands in it (#77).
     for w in host.windows():
         if w['address'] not in wins:
             api.run('window', {'generation': gen, 'action': 'close',
                                'address': w['address']})
     ```
   - → verify:
     - `python -m py_compile tests/smoke.py`;
     - `python -m pytest tests/ -q`;
     - `nix flake check` (CI's `check`).
   - Traps:
     - `host` and `api` are already imported in `check_wait` (line ~121).
     - `gen` is defined before the loop (line ~137).
     - Don't widen the `try`: a failed close must propagate.

2. **Live checks on p620** (lead, with your control granted, in your live session):
   - **Forced case:** a throwaway script, not committed:
     - monkeypatch `index.plugins` to return one enabled `panel` candidate whose
       `opens_with` is the terminal key from `index` (e.g. `SUPER + Return`);
     - run `smoke.check_wait()`;
     - record `host.windows()` addresses before and after: they must be equal
       (the run itself then raises "no panel appeared", which is expected).
   - **Normal run:** `python tests/smoke.py` passes `check_wait`.
   - Put both outputs in the PR.
   - Traps: the herdr pane may hold a stale Hyprland signature after a Hyprland
     restart, so check `ai-mirror status` before driving.

3. **PR and issue.**
   - The PR links intent, spec and plan.
   - Comment on #77 that the layer pick is left out (latent, no host shows it).
   - Run `gh pr update-branch` before merge, since master is protected and
     `check` is required.
   - After merge, nixarchy tracks ai-mirror master. Bump it on the next deploy:
     the smoke run isn't shipped, so no deploy is needed for this alone.

## Tests

```bash
python -m pytest tests/ -q
nix flake check
```

## Rollback

Revert the PR. It touches only the smoke script, which isn't shipped.
