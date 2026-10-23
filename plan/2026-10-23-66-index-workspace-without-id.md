---
status: draft
issue: 66
spec: spec/2026-10-23-66-index-workspace-without-id.md
---

# Plan: one workspace without an id must not blank the index

Self-contained. Branch `fix/66-index-workspace-without-id`. Line numbers as of
`141d5ef`.

## Approved decisions (from the spec)

1. `state()` keeps `workspaces` and `occupied` as sorted lists of **int** ids
   (`type(id) is int`, so not bool or None).
2. Every entry without an int id goes into `named`: `{name, windows}`, name
   `str(w.get('name') or '?')[:80]`, `windows` from `_holds(w)`.
3. `_holds(w)` = `type(w.get('windows')) is int and w['windows'] > 0`; it also
   decides `occupied`.
4. Non-dict entries are skipped. No field of an entry may raise.
5. Markdown: "workspaces in use: [ids]" gains " and <name>, <name>" for named
   workspaces that hold a window; unchanged otherwise.

## Steps

1. **`src/ai_mirror/index.py:70-84` `state()`.** Add `_holds` just above
   `state()`. Replace the body after `version = ...`:
   ```python
   workspaces = [w for w in json.loads(sh('hyprctl', 'workspaces', '-j')) if isinstance(w, dict)]
   numbered = [w for w in workspaces if type(w.get('id')) is int]
   ```
   and the two list keys plus a new `'named'` as in decision 2, with a
   one-line comment citing #66 (Omarchy's screensaver workspace has no id).
   **Render (`index.py:429`):** build the line from `section['occupied']` and
   the names of `section.get('named', [])` entries whose `windows` is true.
   → verify by `python3 -m unittest discover -s tests`.
   Traps: `index` is read-only and ungated; `_render_section` must still work
   for a `state` without `named` (use `.get`). Stdlib only.

2. **`tests/test_invariants.py`, class `DesktopIndex` (line 376).** One test:
   patch `index.sh` to return `'Hyprland 0.56.2 built from x\n'` for
   `('hyprctl','version')` and the fixture from the spec for
   `('hyprctl','workspaces','-j')`, and `host.monitors` to `[]`. Fixture:
   `[{"id": 1, "name": "1", "windows": 2}, {"name": "special:screensaver-HDMI-A-1", "windows": 1}, {"id": null, "name": "x"}, {"id": 3}, {"id": "4", "name": 7, "windows": "0"}, {"id": true}, "junk"]`.
   Assert: no `_unavailable`; `workspaces == [1, 3]`; `occupied == [1]`;
   `named` == screensaver (`True`), `x`, `7`, `?` (all `False`) in that order;
   `index.render({'state': out})` contains `special:screensaver-HDMI-A-1` and
   not `'x'`-only names. → verify by the unittest command; confirm it fails on
   the old `state()` (KeyError) before step 1 is applied.
   Traps: `sh` takes `*argv`; dispatch on the args tuple. Check how
   `index.render` expects its input (`index.build` output shape) before
   asserting on it.

3. **Live.** `ai-mirror index --section state` on this desktop (screensaver
   workspace present) renders the section and names it. → verify by eye.

## Execution

Two editing steps, two files: below the coder threshold, so the session model
implements them, with `codex review --uncommitted` and agy checking the diff
before commit.

## Tests

```sh
python3 -m unittest discover -s tests -v
nix flake check
```

## Rollback

Revert the commits. No state or config changes.
