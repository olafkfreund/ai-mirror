# Using ai-mirror

## Control model

`$XDG_RUNTIME_DIR/ai-mirror/state.json` holds `{owner: agent|pending|off, generation, since, enabled_by}`.

- **Control is asked for, not taken.** `control agent` — from an agent, the CLI or the bar —
  writes `owner: pending` with a `request {id, by, since, expires}` and opens a dialog on your
  desktop. Only you answer it: **A** allows, **Escape** (or Enter, or Deny) refuses. An
  unanswered request lapses after 30 seconds and the state goes back to `off`.
- A confirmed grant records `enabled_by: "human-confirmed"` and `request_by` (who asked).
  An agent cannot answer its own request: `control confirm|deny` over MCP is `not_owner`, and
  no confirm tool exists.
- **A grant expires.** It ends when the asking MCP server exits, when you stop it, and by
  itself after ten minutes with no input (`not_owner`, "ask again").
- While an agent only *looks*, `watching` records when it last did and the bar shows a steady
  neutral mark: reading the screen is visible, even though it needs no grant.
- Every request, answer, expiry and stop is one JSON line in
  `$XDG_RUNTIME_DIR/ai-mirror/audit.jsonl`.
- Every change bumps `generation`. Screenshots and input carry the generation they were made
  under; input from an older generation is refused with `stale_generation`.
- Input, `window`, `launch`, `a11y_act` and clipboard writes need `owner: agent` (`not_owner` otherwise).
  Observation (`status`, `screenshot`, `windows`, `a11y_tree`, `a11y_find`, clipboard read) always works.
- Ownership is re-checked before every single low-level input event, so a stop lands mid-batch.
  A batch that stops that way reports how much of it was delivered first: `partial: 9 of 14 lines
  delivered (actions 1-2 of 3 completed), ...`, with `delivered`, `of`, `actions_completed` and
  `actions_total` beside the message. Only a plain `input was NOT sent`, with no counts, means
  nothing landed (#30).
- **Stop** = `ai-mirror control off`, bound to Super+Shift+Escape and to clicking the bar indicator.
  It writes the state and signals every running `ai-mirror mcp`, whose input helper then releases
  all held keys and buttons and exits.
- The state lives in the runtime dir: it is gone after logout, so control is never on at login.

## MCP tools

| Tool | Purpose |
|---|---|
| `status` | owner, generation, monitors `{name,x,y,w,h,scale,focused}` |
| `control` | `mode: agent\|off` — `agent` asks the human; poll `status` until `owner` is `agent` or `off` |
| `screenshot` | `output` (monitor name or `all`, default focused), `region [x,y,w,h]` global px, `max_size` 320–3840 (default 1280), `image` |
| `windows` | address, class, title, `at`, `size`, monitor, workspace, floating, fullscreen |
| `input` | `frame` (image px) or `generation` (global px), `actions[1..16]`, `screenshot`, `wait_ms` |
| `window` | `action: focus\|close\|float\|center\|fullscreen\|workspace\|resize`, `address`, `mode`, `workspace`, `w`, `h` |
| `launch` | `argv` — no shell |
| `clipboard` | `action: read\|write`, `text` |
| `a11y_tree` | `app`, `depth`, `max_nodes` |
| `a11y_find` | `name` (substring), `role` (exact, e.g. `push button`, `entry`, `link`), `app`, `limit` |
| `a11y_act` | `node`, `action: click\|focus\|set_text\|<action name>`, `text`, `expect {role,name}` |

### Input actions

| type | fields |
|---|---|
| `move` | `x`, `y` |
| `click` | `x`, `y`, `button` (left/right/middle/back/forward), `count` 1–3 |
| `drag` | `x`, `y`, then `to_x`/`to_y` or `path: [[x,y], …]` (≤32 points, emits intermediate motion) |
| `scroll` | `dx`, `dy` steps (positive = right/down), optional `x`, `y` |
| `type` | `text` — Unicode, `\n` and `\t`, ≤4096 UTF-8 bytes, independent of keyboard layout |
| `key` | `keys: ["CTRL","SHIFT","T"]` pressed in order, released in reverse |
| `key_down` / `key_up` | `keys` — hold or release across calls |
| `mouse_down` / `mouse_up` | `button`, optional `x`, `y` |

Any action accepts `modifiers: ["SHIFT"]`, held around it (shift-click, ctrl-drag, ctrl-scroll).
Key names are Linux evdev names without `KEY_` (`CAPSLOCK`, `KP5`, `F24`, `PLAYPAUSE`, `SYSRQ`)
plus aliases `CTRL SHIFT ALT SUPER META WIN ESC RETURN PRINT MENU PGUP PGDN DEL` and single
characters `- = [ ] ; ' \` , . /`. Key codes follow a US layout; use `type` for text.

## Coordinates

Everything is in Hyprland's global layout pixels (`hyprctl monitors`: `x`, `y` plus logical size).
A screenshot's `frame` remembers its region and scale; pass it to `input` and use coordinates
straight from the image. `region` zooms into detail. `a11y` bounds are screen coordinates as the
toolkit reports them — on Wayland some toolkits report window-relative values, so prefer
`a11y_act` over clicking a11y bounds.

## CLI

Every command prints JSON; errors are `{"error":{"code","message"}}` with a nonzero exit.

```sh
ai-mirror status
ai-mirror control agent|off              # agent asks; off revokes
ai-mirror control confirm|deny [ID]      # answer the waiting request (what the dialog runs)
ai-mirror screenshot [--output DP-1|all] [--region x,y,w,h] [--max-size N] [--out file.png]
ai-mirror windows
ai-mirror input --generation N '[{"type":"click","x":300,"y":200,"modifiers":["CTRL"]}]'
ai-mirror window focus|close|float|center|fullscreen|workspace|resize 0x55d1… [--mode maximized] [--workspace 3] [--w 800 --h 600]
ai-mirror launch -- firefox https://example.com
ai-mirror clipboard read | ai-mirror clipboard write "text"
ai-mirror a11y-tree [--app firefox] [--depth 12] [--max-nodes 400]
ai-mirror a11y-find --name Save [--role "push button"]
ai-mirror a11y-act 3.0.2.1 click | ai-mirror a11y-act 3.0.2.4 set_text --text hello
ai-mirror doctor
ai-mirror mcp
```

## Accessibility per toolkit

The Home Manager option sets `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`, `GTK_MODULES=gail:atk-bridge`
and `toolkit-accessibility`; ai-mirror also sets the AT-SPI `IsEnabled` flag on first use.

- GTK and Qt apps: work after a re-login (apps started before need a restart).
- Firefox: restart it after `IsEnabled` is set.
- Chromium, Chrome, Electron (VS Code, Slack…): start with `--force-renderer-accessibility`.

## Troubleshooting

- `not_owner` — ask for control (`control agent`) and wait for the human to allow it; after ten
  idle minutes a grant ends and has to be asked for again. `stale_generation` — control changed;
  take a new screenshot. `wrong_target` — control is still yours, but the thing you aimed at is not
  the one that can be typed into: another window has focus, or a surface opened since the grant and
  may hold the keyboard. Observe and aim again, or wait for the surface to go (#31, #29).
- `doctor` says `ok: false` with `compositor` and `unset` when the shell has no desktop session —
  the usual cause of every command failing at once over ssh (#32). `demo/rz` shows what to export.
- The middle mouse button works — `wev` sees `274 (middle)` and alacritty pastes the primary
  selection from it — but **Chrome ignores it** (a tab does not close, a link does not open in a
  background tab) while `left` and `right` work in the same window. GNOME applications do not paste
  on middle click either, because GNOME sets `gtk-enable-primary-paste = false`; that is the
  desktop, not the event. Use `CTRL+W` and `CTRL+click` in Chrome (#37).
- No dialog appears — the bar widget draws it, so enable the plugin
  (`omarchy plugin enable olafkfreund.ai-mirror --section right`). With it disabled, nobody can
  answer and every request lapses after 30 seconds; `ai-mirror control confirm` from a terminal
  is the way out.
- `ai-mirror-input helper not found` — use the flake package, or set `AI_MIRROR_HELPER`.
- Indicator missing — `omarchy plugin enable olafkfreund.ai-mirror --section right`.
- Kill switch key does nothing — add `pcall(require, "hypr.ai-mirror-binds")` to `bindings.lua`.
- `ai-mirror doctor` lists missing runtime commands.
