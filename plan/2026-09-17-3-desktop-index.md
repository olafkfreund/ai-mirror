---
status: draft
issue: 3
spec: spec/2026-09-17-3-desktop-index.md
---

# Plan: A desktop index, so an agent stops rediscovering this host

## The approved decisions, carried

Implementable without opening the intent or the spec.

**What is built.** `ai-mirror index` (CLI) and `desktop_index` (MCP tool) over
a shared `index.py`. Markdown by default because the reader is usually a
language model; `--json` for programs.

**Sections.** Default set is `state`, `keys`, `plugins`, `nav`, `gotchas`.
`apps` only on `--section apps`. `commands` is never returned whole — `--find
<query>` searches the 459 `omarchy-*` summaries instead. The default must stay
small or callers stop asking for it.

**Keys come from `~/.config/hypr/*.lua`,** not `hyprctl binds`. The config
carries key, human label and command together:

```lua
o.bind("SUPER + ALT + N", "nixarchy packages", "omarchy-shell shell toggle nixarchy.pkg '{}'")
```

36 of these across six files. `hyprctl binds` returns 4920 entries with no
labels and opaque arguments; it is consulted only for a count, so the index can
say when parsing found suspiciously few.

**The join.** A bind's command often names a plugin id. Matching it against the
plugin list gives every plugin its opening keystroke with nothing to maintain.
This is the fact whose absence caused a guessed keybinding to change the
wallpaper mid-recording.

**Navigation strategy, never coordinates.** Classify each application live from
the a11y tree: children present → `a11y`, none → `keyboard`. QuickShell reports
no children, so the whole shell is keyboard-driven. Coordinates drift when the
tray expands under the cursor and must not be recorded as fact.

**Reuse before reimplementation.** `omarchy-plugin-list`, `omarchy-theme-list`
and `nixarchy-pkg state` already enumerate their domains. Parse files only
where no command exists.

**Four standing rules.** No cache (regenerate per call; nothing to invalidate).
No disk writes (stdout or return value only — this is what keeps application
lists and session titles out of a commit). No control gate on reading. Degrade
per section with `_unavailable: <reason>` rather than raising.

**One refinement to the spec.** The spec said `index/gotchas.md`; this plan
puts it at `src/ai_mirror/gotchas.md`. `flake.nix` installs with
`cp -r ai_mirror $out/lib/`, so a file inside the package directory is packaged
with no flake change at all, while a top-level `index/` would need one. Same
file, same hand-written-only rule, less machinery.

## Steps

1. `src/ai_mirror/gotchas.md`: new. The lessons that cannot be derived — the
   tray expanding under a hovering cursor; `Return` on a boolean row in the
   package panel writing to `~/.config/nixarchy/*.nix`; `herdr` refusing to
   nest without `HERDR_*` stripped; Escape being swallowed by a focused search
   field where `omarchy-shell shell hide <id>` is idempotent; Hyprland 0.56
   taking Lua dispatch. Hand-written, human-reviewed, never machine-edited.
   → verify by `test -s src/ai_mirror/gotchas.md`

2. `src/ai_mirror/index.py`: new. One function per section, each returning a
   dict and each wrapped so a failure yields `{'_unavailable': reason}`.
   `build(args)` assembles the requested sections; `render(data)` formats
   Markdown. Stdlib only.
   → verify by `python3 -c "import sys; sys.path.insert(0,'src');
     from ai_mirror import index; d=index.build({});
     print(sorted(d), len(d['keys']['binds']), len(d['plugins']['items']))"`
     printing the five default sections with non-zero counts

3. `src/ai_mirror/api.py`: add `if op == 'index': from . import index; return
   index.build(args)` among the read-only operations, above the `MUTATING`
   branch so no ownership gate applies.
   → verify by `ai-mirror index --json | head` with control off

4. `src/ai_mirror/cli.py`: add the `index` subparser with `--section` (repeat‑
   able), `--find`, `--json`. Markdown to stdout unless `--json`.
   → verify by `ai-mirror index`, `ai-mirror index --section apps`,
     `ai-mirror index --find theme` each printing plausible output

5. `src/ai_mirror/mcp.py`: add a `desktop_index` entry to `TOOLS`, and one
   sentence to `INSTRUCTIONS` telling the agent to call it before its first
   desktop action. The instructions are the delivery mechanism — an index no
   one is told about is an index no one calls.
   → verify by `tools/list` over stdio listing `desktop_index`

6. `tests/test_invariants.py`: fast, no Wayland. Fixture `bindings.lua` yields
   expected key/label/command rows; a fixture manifest directory yields
   expected plugins; the key→plugin join resolves; a missing file degrades to
   `_unavailable` instead of raising; default Markdown stays under the byte
   budget.
   → verify by `python3 -m unittest discover -s tests -v`

7. `tests/smoke.py`: live assertions so a silently empty parser fails loudly —
   at least 30 keys, at least 20 plugins, `nav` classifying quickshell as
   `keyboard`, all five default sections present.
   → verify by running it on this host

8. `AGENTS.md`: a code-map row for `index.py`, and a line under "Driving this
   desktop" pointing at `ai-mirror index` so the prose stops being the primary
   source for what the command now answers.
   → verify by reading the diff

9. `flake.nix`: no change expected. Confirm rather than assume.
   → verify by `test -f "$(nix build .#ai-mirror --print-out-paths)/lib/ai_mirror/gotchas.md"`

## Tests

```sh
python3 -m unittest discover -s tests -v   # all pass, including the new cases
nix build .#ai-mirror .#ai-mirror-input .#plugin
nix flake check
ai-mirror index                            # five sections, control off
ai-mirror index --find theme               # matches omarchy-theme-set et al
python3 tests/smoke.py                     # live; moves the mouse
```

Acceptance, and the only test that measures the point: an agent given nothing
but `desktop_index` — no screenshots, no grepping — opens the package panel and
reaches the Options tab for PostgreSQL. That is the sequence that failed in the
session behind this issue.

## Rollback

`git revert` the implementation commits. Nothing to undo beyond that: the
feature writes no files, creates no state, starts no service and runs no
migration. An agent that had been calling `desktop_index` gets an unknown-tool
error and falls back to what it does today.

The one change already made outside this branch is that Issues were enabled on
this repository so #3 could exist; that is unrelated to the code and stays.
