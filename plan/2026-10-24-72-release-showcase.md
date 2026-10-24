---
status: approved
issue: 72
spec: spec/2026-10-24-72-release-showcase.md
---

# Plan: release 3.0.0 and show the agent working without your cursor

Self-contained. Branch `docs/72-release-showcase` from master `6b133c6`.

## Approved decisions (from the spec)

1. **Version 3.0.0.** The required `generation` breaks callers. Release
   notes, in order: Breaking (`generation` on every mutating call, where to
   get it, the error text), New (`set_value`, `select`, `value` rows,
   read-back everywhere, clicks only named click actions), Fixed (#66, #68),
   then links to the measured table and the showcase.
2. **README:** the Understand row says "without the pointer" and "reads
   each result back". A new section, "Work in a window you are not using",
   names the limits (still a grant, red mark; page-owned ARIA state and
   Chrome spin buttons give `not_confirmed`; GTK4 text unreadable) and
   links `src/ai_mirror/gotchas.md`. The showcase goes above the existing
   video.
3. **usage.md:** one paragraph on background use, `not_confirmed` cases
   and Firefox needing a visible workspace. No new table.
4. **Showcase:** `demo/background.sh` plus `demo/background.html`, run
   locally in Chrome only. Each step prints `verified`, `hyprctl cursorpos`
   and the focused window. The script exits non-zero if a step is not
   verified or the cursor or focus moved.
   - mp4 ≤ 10 MB (1280x720, crf 26).
   - GIF ≤ 5 MB (960 px, 10 fps, palette pass); cut to three steps if over.
   - Plus a poster JPEG.

## Steps

1. **Version.** Change `2.1.0` to `3.0.0` in `flake.nix:11`,
   `src/ai_mirror/__init__.py:3` and `plugin/manifest.json:5`.
   → verify by `nix eval --raw .#ai-mirror.version` printing `3.0.0`, and
   `grep -rn '2\.1\.0' flake.nix src plugin` printing nothing.
   Traps: `flake.nix:132` validates the manifest with `jq`, so keep it
   valid JSON.

2. **`demo/background.html` and `demo/background.sh`.**
   - **The page:** title "ai-mirror background demo"; contains:
     - `<label>Volume <input type=range min=0 max=10 step=1 value=3></label>`
     - `<label>Size <select size=4>` with Small / Medium (selected) /
       Large / Huge
     - `<label><input type=checkbox> Notify</label>`
     - `<button>Save</button>`
     - `<output id=out aria-live=polite>`
     On Save, a tiny inline script writes
     `Saved: volume <v>, size <s>, notify <on|off>` into it. No external
     resources.
   - **The script:** `#!/usr/bin/env bash`, `set -u`, and the CLI from
     `${AI_MIRROR:-ai-mirror}`. In order:
     1. Record `HOME_WIN` from `hyprctl activewindow -j` (the terminal the
        script runs in).
     2. Run `ai-mirror control agent` and poll `status` once a second for
        up to 35 s. Anything other than `owner: agent` prints "no grant"
        and exits 1.
     3. `omarchy-toggle-notification-silencing`. A `trap` on EXIT
        un-silences, kills the recorder with SIGINT and waits for it,
        closes the Chrome window through `ai-mirror window close`, and
        runs `ai-mirror control off`.
     4. `ai-mirror launch --generation $G -- google-chrome-stable
        --user-data-dir=$TMP/ch --no-first-run --no-default-browser-check
        --force-renderer-accessibility --new-window file://<abs page>`.
        Move the window to the terminal's workspace, then
        `ai-mirror window --generation $G focus $HOME_WIN`.
     5. If `REC` is set, start `gpu-screen-recorder -w ${MON} -f 30 -k
        h264 -q very_high -o "$REC"` in the background, `MON` defaulting to
        the focused monitor.
     6. Poll `ai-mirror a11y-find --app chrome --name Volume` until a
        slider appears (≤ 20 s).
     7. Run each step through `ai-mirror a11y-act --generation $G`:
        - `set_value --value 7` on the slider
        - `select` on the list item `Large`, with
          `--expect '{"role":"list item","name":"Large"}'`
        - `click` on the check box `Notify`
        - `click` on the button `Save`
     8. Then read the `Saved:` text with `a11y-find --name Saved` (the
        output's text or name).
     9. After each step print one line: action, target, `verified`/`ok`,
        `cursor X,Y`, `focused: <class>`. A `set_value`/`select` with
        `verified` not true, or a cursor or active address different from
        the first reading, sets `FAIL=1`.
     10. `sleep 2`, then `exit $FAIL`.
     The JSON is parsed with `python3 -c`, as `demo.sh` does.
   - **`demo/README.md`** gains "Re-record the background showcase": the
     `REC=... MON=HDMI-A-1 demo/background.sh` line and the two ffmpeg
     commands from decision 4:
     - `-vf scale=1280:-2 -crf 26 -preset slow -movflags +faststart`
     - GIF: `fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse`
   → verify by `bash -n demo/background.sh`, and a run with control off
   and no answer exiting 1 with "no grant" (the dialog appears; nobody
   presses A). Confirm `control` is `off` afterwards.
   Traps:
   - Never `hyprctl dispatch` a free-form string; use the CLI's `window`.
   - Chrome's `click` moves in-page focus (measured); that is fine and
     not window focus.

3. **README and usage.**
   - `README.md:71`: the Understand row becomes "`a11y_tree` / `a11y_find`
     list buttons, fields and links by role and name · `a11y_act` clicks,
     fills, sets sliders and picks list items **without the pointer**, and
     reads each result back".
   - After the table, a `## Work in a window you are not using` section
     (decision 2), at most about 12 lines, linking
     `src/ai_mirror/gotchas.md`.
   - Above the existing poster (`README.md:29`):
     `[![...](assets/demo-background-poster.jpg)](assets/demo-background.mp4)`
     with a `<sub>` caption in the existing style, and the GIF under it.
   - `docs/usage.md`: one paragraph in the accessibility notes before the
     middle-mouse bullet (`docs/usage.md:129`), per decision 3.
   → verify by `python3 -m unittest discover -s tests` (the index-size test
   is unaffected) and by checking every new relative link exists after
   step 4.
   Traps: the README claims only what the measured table says.

4. **Record (session model, live, under the human's grant).** On HDMI-A-1
   (1920x1080, not the human's working monitor), switch to an empty
   workspace 25. Open a terminal there and run
   `REC=<scratch>/raw.mp4 MON=HDMI-A-1 demo/background.sh`; the human
   presses A. Then run the step 2 ffmpeg commands into
   `assets/demo-background.mp4` and `assets/demo-background.gif`, plus
   `ffmpeg -ss 6 -frames:v 1 -q:v 3 assets/demo-background-poster.jpg`.
   Afterwards, switch HDMI-A-1 back to workspace 21.
   → verify by:
   - the script's exit 0
   - `ls -l assets/demo-background.*` within the limits
   - watching the mp4: the cursor line is constant and the page ends
     "Saved: volume 7, size Large, notify on"
   Traps:
   - Silence notifications (the script does).
   - A fresh scratch Chrome profile, never the real one.
   - Close every test window.

5. **PR, merge, tag, release (session model).**
   1. Open a PR linking intent, spec and plan, and saying which steps the
      coder did.
   2. Wait for CI and merge it.
   3. Tag the merge commit `v3.0.0` and push the tag.
   4. Run `gh release create v3.0.0 --title "3.0.0" --notes-file <notes>`,
      with the notes from decision 1. Attach the mp4.
   → verify by `gh release view v3.0.0`.

## Execution

Steps 1-3 edit seven files: one `coder` agent does them in order. It
cannot commit; the session model commits each step, naming it. Steps 4-5 are
the session model's. A fresh Opus review compares
`git diff master...HEAD` with this plan before the PR.

## Tests

```sh
python3 -m unittest discover -s tests -v
nix flake check
bash -n demo/background.sh
```

## Rollback

Revert the PR. To withdraw the release: `gh release delete v3.0.0 &&
git push origin :v3.0.0`. nixarchy keeps its pin until #1436 moves it.
