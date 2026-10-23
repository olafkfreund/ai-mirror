---
status: draft
issue: 66
intent: intent/2026-10-23-66-index-workspace-without-id.md
---

# Spec: one workspace without an id must not blank the index

## Design

All in `src/ai_mirror/index.py`.

### 1. `state()` reads each workspace defensively (lines 75-84)

```python
workspaces = [w for w in json.loads(sh('hyprctl', 'workspaces', '-j')) if isinstance(w, dict)]
numbered = [w for w in workspaces if type(w.get('id')) is int]
return {
    ...,
    'workspaces': sorted(w['id'] for w in numbered),
    'occupied': sorted(w['id'] for w in numbered if _holds(w)),
    # Hyprland lists some special workspaces (Omarchy's screensaver) with no
    # id at all (#66); they are still somewhere an agent should know about.
    'named': [{'name': str(w.get('name') or '?')[:80], 'windows': _holds(w)}
              for w in workspaces if type(w.get('id')) is not int],
}
```

with `_holds(w)` = `type(w.get('windows')) is int and w['windows'] > 0`, so a
string such as `"0"`, `None` or a bool never counts as holding a window, and
`occupied` uses the same rule it did for real counts.

`type(...) is int` excludes `bool` and `None` as well as a missing key, so
`sorted` never sees mixed types. The name is capped like other app-set text in
the index.

### 2. Markdown shows the occupied named ones (line 429)

`- workspaces in use: [1, 2, 11]` becomes
`- workspaces in use: [1, 2, 11] and special:screensaver-HDMI-A-1` when a named
workspace holds a window; unchanged otherwise.

### 3. Test

In `tests/test_invariants.py`, next to the existing index section tests: stub
`index.sh` so `hyprctl workspaces -j` returns
`[{"id": 1, "name": "1", "windows": 2}, {"name": "special:screensaver-HDMI-A-1", "windows": 1}, {"id": null, "name": "x"}, {"id": 3}, {"id": "4", "name": 7, "windows": "0"}, {"id": true}, "junk"]`
(and `hyprctl version` / `host.monitors` stubbed). Assert `state()` returns
without `_unavailable`, `workspaces == [1, 3]`, `occupied == [1]`, `named`
holds the screensaver (`windows: True`), `x`, `7` and the `true`-id entry all
with `windows: False`, and the rendered Markdown line names the screensaver
and none of the others.

## Alternatives rejected

- **Skip id-less workspaces silently.** Smallest, but the intent wants a
  workspace holding a window to stay visible.
- **Mix names into `workspaces` / `occupied`.** `sorted` of ints and strings
  raises `TypeError`, and readers expect ids.

## Risks

- A reader that iterates every key of `state` sees one new key, `named`.
  Nothing in the repo does; `index` output is read by agents, not parsed.

## Verification

- `python3 -m unittest discover -s tests` green with the new test.
- `nix flake check` green.
- Live: `ai-mirror index --section state` on this desktop renders the section,
  with the screensaver workspace named.
