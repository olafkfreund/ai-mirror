# AGENTS.md

Guide for AI agents working **on** or **with** ai-mirror. `CLAUDE.md` is a symlink to this file.

## What this is

A NixOS/Nixarchy tool that lets an MCP agent control the user's **real** Hyprland desktop
(screens, keyboard, mouse, windows, clipboard, AT-SPI accessibility), with a red bar indicator
and a kill switch. There is no sandbox: correctness of the ownership gate is the safety model.
An earlier sandboxed design (nested desktops for Arch/Omarchy) was removed in 2.0.

## Using it (MCP)

`claude mcp add ai-mirror -- ai-mirror mcp`. Loop: `control agent` → `a11y_find`/`windows`
(cheap) or `screenshot` → `input` with the frame → … → `control off`. On `not_owner` or
`stale_generation`: the human stopped you; stop, observe again, never retry blindly.
Full reference: `docs/usage.md`.

## Code map

| File | Role |
|---|---|
| `bin/ai-mirror` | Checkout launcher → `ai_mirror.cli.main` (the flake wraps `python -m ai_mirror`) |
| `src/ai_mirror/cli.py` | argparse → `api.run`, prints JSON; stops the helper on exit |
| `src/ai_mirror/mcp.py` | Hand-rolled stdio JSON-RPC server: tool schemas + validation, frames (`observe`, `from_frame`), SIGUSR1 → `HELPER.abort()`, revokes agent grants on exit |
| `src/ai_mirror/api.py` | Single dispatcher for CLI/MCP/bar; ownership gate for mutating ops; clipboard, launch |
| `src/ai_mirror/control.py` | State file, `set_owner`, `require_agent`, MCP server registry + `signal_servers`, `Helper` (ai-mirror-input process), `run_batch`, `screenshot` (grim) |
| `src/ai_mirror/host.py` | `hyprctl`: monitors, `layout_box`, windows, `window_dispatch` (validated Lua) |
| `src/ai_mirror/input.py` | Actions → helper lines `M x y` / `B code 0\|1` / `S dx dy` / `K code 0\|1` / `T utf8`; evdev key table |
| `src/ai_mirror/a11y.py` | AT-SPI via `gi.repository.Atspi`: tree, find, act |
| `src/ai_mirror_input/ai_mirror_input.c` | Persistent wlr virtual pointer + virtual keyboard; `C` releases all; stdin EOF releases and exits |
| `plugin/` | Omarchy bar widget: `FileView` on the state file, click toggles control; `@ai-mirror@` substituted by Nix |
| `flake.nix` | `packages.{ai-mirror,ai-mirror-input,plugin}`, `homeManagerModules.default`, `checks`, `devShells` |
| `tests/test_invariants.py` | Fast regressions (no Wayland); `tests/smoke.py` live desktop check |

## Invariants — do not break

- **Generation + owner gate all mutating operations.** `set_owner` bumps generation on every change.
- **`run_batch` re-reads the state before every helper line** and sends `C` (release all) on
  *every* failure path — state change, helper error, non-`OK` ack.
- **Kill switch = state write + SIGUSR1** to pid-verified servers in `ai-mirror/mcp.d/`. Only the
  process that owns a virtual keyboard can release it, so the signal closes the helper's stdin.
- **No free-form string reaches `hyprctl dispatch`.** Addresses, workspaces, ints and enums are
  validated in `host.window_dispatch`. `launch` uses argv without a shell.
- **Nothing inherits the MCP stdout** (the JSON-RPC channel): child processes get `DEVNULL`
  (`wl-copy` forks a long-lived daemon).
- **Unexpected exceptions never kill the MCP server**: tool errors become `isError` results,
  protocol errors `-32603`; only unknown methods are `-32601`.
- Every coordinate goes through `input.point` (integer, non-negative).
- The plugin directory contains no symlinks (Nixarchy's validator rejects them).

## Develop

```sh
nix develop
python3 -m unittest discover -s tests -v
nix flake check
nix build .#ai-mirror .#ai-mirror-input .#plugin
AI_MIRROR_HELPER=$(nix build .#ai-mirror-input --print-out-paths)/bin/ai-mirror-input python3 tests/smoke.py   # moves the mouse
```

Style: stdlib Python (PyGObject only for a11y), JSON in/out, small functions, no new
dependencies. New tool = `api.run` branch + `mcp.TOOLS` entry + CLI subcommand + test.
