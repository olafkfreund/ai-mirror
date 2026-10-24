---
status: draft
issue: 72
intent: intent/2026-10-24-72-release-showcase.md
---

# Spec: release 3.0.0 and show the agent working without your cursor

## Design

### 1. Version 3.0.0

Bump the three places the 2.1.0 release touched (PR #63): `flake.nix:11`
(`version = "2.1.0"`), `src/ai_mirror/__init__.py:3`, and
`plugin/manifest.json:5`. Once the docs PR has merged, tag the merge commit
`v3.0.0` and publish a GitHub release. The notes run in this order:

1. **Breaking:** every mutating call (`input`, `window`, `launch`, agent
   clipboard write, `a11y_act`) needs `generation`, which `status`,
   `windows`, `a11y_find`, `a11y_tree` and screenshot frames all return. An
   old call fails with "generation is required -- ...". To adapt, read
   `generation` from the last observation and pass it.
2. **New:** `a11y_act set_value` / `select`, `value` in rows, and read-back
   for every write, with `verified`, `changed`, `not_confirmed` and
   `details.delivered`. Clicks run only named click actions.
3. **Fixed:** #66 (index on a special workspace), #68 (key-up after its
   target closes).
4. A link to the measured table, and the showcase.

### 2. README

- The **Understand** row of "What an agent can do" (`README.md:71`) becomes:
  "`a11y_act` clicks, fills, sets sliders and picks list items **without
  the pointer**, and reads each result back".
- A new short section, "Work in a window you are not using", after that
  table. It says the agent can act through the accessibility tree on a
  window that has no focus, so your cursor and keyboard stay yours. It
  links `src/ai_mirror/gotchas.md`'s measured table for which apps do what.
  It names the limits: control is still a grant and the bar mark is red;
  page-owned ARIA state and Chrome spin buttons give `not_confirmed`;
  GTK4 text can't be read back.
- The showcase is embedded above the existing 84-second video, as a poster
  linking the mp4, with the GIF inline.

### 3. `docs/usage.md`

The `a11y_act` row is already current (#70 step 5). Add one paragraph to
the accessibility notes near `docs/usage.md:130`: background use, the
`not_confirmed` cases, and that a Firefox window must be on a visible
workspace (measured in #65). No new table.

### 4. The showcase

`demo/background.sh` uses the local `ai-mirror` CLI on this host, not the
`rz` ssh wrapper `demo.sh` uses, and `demo/background.html` is the page it
drives: a slider, a native `<select size=4>`, a check box, a Save button and
an output line the page fills on Save.

It records one monitor with `gpu-screen-recorder` (AGENTS.md recipe, 30
fps, no audio). On that monitor are a Chrome window (scratch profile,
`--force-renderer-accessibility`) and a focused terminal. The terminal
runs the script, and the script prints each step:

```
set_value Volume 3 -> 7   verified   cursor 1203,644   focused: terminal
select    Size: Large     verified   cursor 1203,644   focused: terminal
click     Notify          ...
click     Save            -> page says "Saved: volume 7, size Large, notify on"
```

The cursor and the focused window come from `hyprctl cursorpos` and
`activewindow` after each step, so the video shows the claim instead of
just stating it. Chrome is the browser because it is the one measured
not to move the pointer.

The script asks for control through the dialog, polls `status`, refuses
to start without `owner: agent`, and runs `control off` and closes its
windows on exit (a `trap`).

- **Outputs:** `assets/demo-background.mp4` (≤ 10 MB: crf 26 at 1280x720),
  `assets/demo-background.gif` (≤ 5 MB: 960 px wide, 10 fps, palette pass),
  and a poster JPEG.
- `demo/README.md` gains a "Re-record the background showcase" block.

## Alternatives rejected

- **2.2.0:** the required `generation` breaks every existing caller.
  Decided in the intent.
- **Firefox in the video:** in #70 step 1 its cursor position changed
  during a write and the cause was unattributed. A showcase must not rest
  on an unclear measurement.
- **Show the human typing live:** that needs a person on camera and adds
  nothing the printed cursor and focus lines don't already prove.
- **Extending `demo.sh`:** it drives another host over ssh and takes the
  pointer on purpose. Its story is input; this one is background work.

## Risks

- **Old callers:** a caller pinned to `github:olafkfreund/ai-mirror`
  without a rev gets the break on update. The release notes lead with it.
  In nixarchy and nixarchy-voice nothing calls a gated op (checked: voice
  uses only `ai-mirror-input`).
- **Notifications:** one landing during recording means re-recording,
  because the script silences notifications and restores them on exit.
- **GIF size:** if it exceeds 5 MB, cut it to the first three steps.

## Verification

- `python3 -m unittest discover -s tests` passes, `nix flake check` passes,
  and `nix build .#ai-mirror` reports 3.0.0
  (`result/bin/ai-mirror --version` or the store path name).
- `bash -n demo/background.sh`, and a dry run with control off: it refuses
  and exits non-zero.
- The recording itself: every printed step says `verified`, the cursor
  line is identical on every step, and focus stays on the terminal.
  Checked by watching the mp4 and by the script's own exit status (non-zero
  if any step isn't verified or the cursor or focus moved).
- File sizes are within the limits above.
- The tag `v3.0.0` points at the merge commit, and `gh release view v3.0.0`
  shows the notes.
