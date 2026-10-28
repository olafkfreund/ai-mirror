---
status: approved
issue: 81
author: olafkfreund
---

# Intent: ai-mirror keeps working after Hyprland restarts

## Problem

ai-mirror reaches the compositor through `hyprctl` (`src/ai_mirror/host.py:19`), which picks its
socket from the `HYPRLAND_INSTANCE_SIGNATURE` it inherited. Each Hyprland start gets a new
signature, and a process started under the old one keeps the old one forever.

On p620 (2026-10-28) that broke every tool. The herdr server started on Oct 22 and has outlived
two Hyprland restarts. Every pane it opens inherits its frozen signature, and so do Claude Code
and the ai-mirror MCP server started in that pane. Every call failed with
`Couldn't connect to /run/user/1000/hypr/<old>/.socket.sock`.

The recovery was not obvious, and took three tries:

- Restarting Claude Code in the same pane changed nothing.
- `$(ls …)` substitution came through empty.
- Only an explicit `export HYPRLAND_INSTANCE_SIGNATURE=<live>` before `claude --resume` worked.

The live value was in `systemctl --user show-environment` the whole time.

## Proposed outcome

- An ai-mirror server whose inherited signature points at a dead socket finds the running
  Hyprland and works, without anyone restarting it or editing its environment.
- When it can't find one, its error says what happened ("Hyprland was restarted; this process has
  the old session") and how to recover, instead of the bare socket error.
- `doctor` reports a stale signature as such, not as "unset".

## Affected users and systems

- Every ai-mirror user whose MCP server is long-lived or started from a long-lived parent
  (herdr, tmux, a systemd unit) across a Hyprland restart.
- Hosts: p620 seen; any Nixarchy host can hit it.
- Tools: every MCP tool and CLI subcommand (all go through `host.py`).

## Constraints

- The ownership gate and its generations must not change. A new Hyprland instance must not
  inherit an old grant. Whether a grant survives a compositor restart at all is for the spec.
- Never attach to another user's or another seat's compositor. Only sockets under this user's
  `$XDG_RUNTIME_DIR/hypr/` count.
- With more than one live Hyprland instance (nested sessions, tests), it must pick
  deterministically, or refuse and say why.
- No polling loop added to the idle path.

## Open questions

- Should the fix live only in ai-mirror, or should nixarchy also refresh the variable in shells
  that herdr starts? The second covers every Wayland tool, not only ai-mirror. It is a separate
  nixarchy issue if wanted.
- When the signature changes under a live agent grant, should ai-mirror revoke the grant
  (safest) or keep it?
