---
status: approved
issue: 100
spec: spec/2026-11-02-100-window-capture.md
---

# Plan: capture one window, including one on a hidden workspace

## Approved decisions (self-contained)

- `screenshot` gets `window: <address>` (MCP, CLI `--window`). It can't be
  combined with `output` or `region` (`ValueError`). No new tool.
- The capture is `grim -T <stableId> [-s scale] dest`. `stableId` comes from
  `hyprctl clients -j` (measured `18000005`) for the window found by address in
  `host.windows()`. Unknown address, missing or non-hex `stableId` → `invalid`,
  and grim is not run. Caller text never reaches grim's argv.
- Privacy: `privacy.kind(class, title)` on that window → `sensitive`, on a
  visible or hidden workspace. `privacy.refuse` (the rectangle check) is not
  used for a window capture.
- Result: today's keys, with `region` = the window's `[*at, *size]` and `output`
  = its monitor, plus `window`, `visible`, `view_only` and `note`.
  `view_only` is true when:
  - its workspace is not visible (decision 1); **or**
  - another window on a visible workspace intersects its box
    (`privacy.covering` minus itself).
- MCP `from_frame` on a `view_only` frame raises `MirrorError('invalid', …)`
  (switch to it and take a fresh screenshot). Nothing is sent.
- No grant, as for `screenshot` (decision 2). `ocr` is unchanged (decision 3).

## Steps

1. `src/ai_mirror/host.py:136`: add `'stableId'` to the `keys` tuple in
   `windows()`.
   → verify `python3 -m unittest discover -s tests`.
   Traps: other callers of `windows()` (`privacy.covering`, `api` windows tool)
   just gain a key. `windows` tool output gains `stableId`, harmless.

2. `src/ai_mirror/control.py:958` `screenshot(dest, output=None, region=None,
   max_size=None, window=None)`: a `window` branch first, before the
   region/output branches.
   - lookup;
   - hex check: `re.fullmatch('[0-9a-f]+', stableId)`;
   - `privacy.kind` → `sensitive`;
   - `visible`;
   - overlap via `privacy.covering(box, [w for w in wins if w['address'] != addr], visible_ws)`;
   - `view_only` and `note`.

   Then the existing max_size validation and scale (from the window's size). The
   grim call becomes `['grim', '-T', stable, *scale_opts, dest]`, and the existing
   `['grim', '-g', …]` stays for the other branches. Keep the PNG read and the
   `MirrorError('unavailable', …)` on failure for both. Add `stdin=subprocess.DEVNULL`
   to the grim call (invariant: nothing inherits MCP stdout). The return dict adds
   the four window keys only in the window branch.
   → verify `python3 -m unittest discover -s tests`.
   Traps:
   - `privacy.covering` skips windows whose workspace is not in `visible`, which
     is what the overlap check wants.
   - Keep the "before grim" refusal comment's meaning: the window privacy check
     runs before grim.
   - `ocr.read` makes its own check. Do not change it.

3. Wiring:
   - `src/ai_mirror/api.py:231` passes `args.get('window')`.
   - `src/ai_mirror/mcp.py:55`: add `'window': STR` to the screenshot schema
     properties, and add the description clause from the spec.
   - `observe` (line 123): add `'window'` to the copied capture keys. `meta`
     copies `window`, `visible`, `view_only` and `note` when present.
   - `from_frame` (line 151): after the frame lookup,
     `if frame.get('view_only'): raise MirrorError('invalid', …)`. Import
     `MirrorError` the way mcp already raises codes (check how `api` errors
     surface; use the same class).
   - `src/ai_mirror/cli.py:78`: `p.add_argument('--window')`.
   → verify `python3 -m unittest discover -s tests` (the tools/list test follows
   `SPECS`).

4. `tests/test_window_capture.py` (new, `Base`), with `host.windows`,
   `host.visible_workspaces`, `host.monitor` and `control.subprocess.run`
   stubbed (a fake grim that writes a tiny valid PNG of the requested size, or a
   PNG header with width/height). Cases are the spec's Verification list:
   - argv;
   - unknown address and non-hex id → `invalid` and no grim;
   - private window → `sensitive` and no grim, visible and hidden;
   - visible and clear → `view_only False`, region = box;
   - hidden → `view_only True`;
   - overlapped → `view_only True` with the note;
   - `window` plus `output` → `ValueError`;
   - `from_frame` on a view-only frame → `invalid`;
   - CLI `screenshot --window` parses.
   → verify `python3 -m unittest discover -s tests`, all pass.
   Traps: `Base` arms the guard; grim is a read and not guarded, so stub
   `subprocess.run` in `control`.

5. Docs: in `docs/usage.md`, the screenshot row gets `window`, `view_only` and
   the privacy note.
   → verify `nix flake check`, `nix build .#ai-mirror`.

6. Live on p620 (me, checkout CLI and MCP):
   - `bin/ai-mirror screenshot --window <visible addr>`: the PNG matches `size`,
     and `view_only` is false.
   - Move a window to an empty hidden workspace (or use one already there),
     capture it: `view_only: true`, the image shows it, and the focused
     workspace is unchanged.
   - Through the MCP server, `input` with that frame → `invalid`, and nothing
     moves. No grant is needed for the captures. The input test needs control,
     so you answer the dialog.

   Record the result here.

## Implementation

Steps 1–5 touch six files: the `coder` agent, as before. I commit each step,
then a fresh Opus agent reviews the diff against this plan. Step 6 is mine.

## Tests

`python3 -m unittest discover -s tests` passes; `nix flake check` passes; step 6.

## Rollback

Revert the merge commit; no state is persisted.

## Deviations during implementation

- Step 1 (coder): no deviation. 400 tests OK.
- Step 2 (coder + me): the coder reported that `hyprctl clients` gives `monitor` as an id; I added `id` to `host.monitors()` rows and the window branch maps it to the output name (measured: 0 → DP-1, 1 → DP-3). 400 tests OK.
- Step 3 (coder): no deviation. 400 tests OK.
- Step 4 (coder): no deviation; 8 tests. 408 tests OK.
- Step 5 (coder): no deviation. nix flake check passed, nix build OK.
