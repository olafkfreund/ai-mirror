---
status: draft
issue: 66
author: olafkfreund
---

# Intent: one workspace without an id must not blank the index

## Problem

`ai-mirror index` is what an agent runs first on an unfamiliar host
(AGENTS.md: "Run `ai-mirror index` first"). On this desktop its `state`
section comes back as `{"_unavailable": "KeyError: 'id'"}`: no Hyprland
version, no dispatch form, no monitors, no workspaces.

The cause is one workspace. Omarchy's screensaver creates
`special:screensaver-HDMI-A-1` with a window in it, and `hyprctl workspaces -j`
returns that workspace with **no `id` key at all**:

```json
{"name":"special:screensaver-HDMI-A-1","monitor":"HDMI-A-1","windows":1}
```

`src/ai_mirror/index.py:82-83` read `w['id']` for every workspace, so a single
entry without one turns the whole section into an error. `tests/smoke.py`
`check_index()` fails on it too. It is not new and not specific to #65; it
appears whenever such a workspace exists.

## Proposed outcome

- `index`'s `state` section renders on a desktop that has a workspace without
  an `id`: version, dispatch form and monitors are all there.
- Such a workspace is still reported, by its name, rather than silently
  dropped -- a screensaver or scratchpad holding a window is something an
  agent should know is there.
- A unit test with a fixture workspace lacking `id` keeps it that way.

## Affected users and systems

- Agents reading `index` (MCP tool and CLI).
- `src/ai_mirror/index.py` (`state()` and its Markdown rendering at line 429),
  a test.
- No change to the ownership gate, input, `wait` (it reads `activeworkspace`,
  not this list) or `host` (it uses workspace names).

## Constraints

- `index` stays read-only and outside the ownership gate.
- The `workspaces` and `occupied` lists keep their current shape for workspaces
  that have an `id`, so existing readers are unaffected.
- No new dependencies.

## Open questions

1. Report id-less workspaces in the same lists (mixing ints and names) or in a
   separate key? Proposed: a separate `named` list, so `workspaces` and
   `occupied` stay lists of ids.
