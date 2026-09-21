---
status: approved
issue: 26
spec: spec/2026-09-21-26-layer-typing.md
---

# Plan: typing into a shell surface, and typing from the CLI

## Approved decisions (from the spec)

- **One parameter.** `window` may name a mapped client (unchanged #24
  path) or a mapped layer surface, by its exact address from
  `hyprctl -j layers`. No `surface` parameter.
- **Observed first.** `host.layers()` returns `address, namespace, monitor,
  level, pid` for every mapped layer, and the `windows` op returns
  `{"windows": [...], "layers": [...]}`.
- **Layer guard, before every line, positive by construction.** It
  proceeds only if (1) the address is a mapped layer now, (2)
  `focused_address()` is `None`, and (3) no other layer is mapped at the
  same level or higher on any monitor. A failed query raises
  `unavailable`; a false condition raises `stale_generation`, with the
  reason chosen after the refusal. Other overlays refuse (retryable, and
  the message names them). Stated limit: a lower layer holding the
  keyboard can't be ruled out.
- **Dispatch:** a client address → `_require_focus` as today. A layer
  address → the layer guard. Neither → `stale_generation` ("not a mapped
  window or surface").
- **CLI:** `input --window ADDRESS`.
- **`index` gotchas** and the MCP descriptions say how to target a surface.
- Measured on razer: `layers -j` costs the same as `activewindow -j` (37 ms
  each through the same wrapper), so a keyboard line pays one more call of
  the size #24 already pays.

## Steps

1. **`src/ai_mirror/host.py`: `layers()`**, after `windows()`. Parse
   `ctl('layers', '-j')`: for each monitor, for each level `"0".."3"`, each
   layer gives
   `{address, namespace[:240], monitor, level: int, pid}`. Keep only
   addresses matching `ADDRESS_RE`. A failed query raises, like
   `focused_address`.
   -> verify by a unit test with the razer shape as the stubbed JSON:
   three layers, levels 0/2/3.

2. **`src/ai_mirror/api.py`**: the `windows` op returns
   `{'windows': host.windows(), 'layers': host.layers()}`.
   -> verify by a unit test on the op's keys.

3. **`src/ai_mirror/control.py`: `_require_target(window)`** replaces the
   `_require_focus(window)` call in `run_batch` (`:418`):
   - read `host.windows()` addresses and `host.layers()` once per line;
     either failing → `unavailable`;
   - address is a client → `_require_focus(window)` (unchanged);
   - address is a layer → `_require_layer(layer, layers)`: refuse unless
     `host.focused_address() is None` and no other layer has
     `level >= layer.level`. The refusal names the focused window or the
     other layer's namespace;
   - neither → `stale_generation`: `{window} is not a mapped window or
     surface now; input was NOT sent. Observe again.`
   The result `note` for a layer says "delivered to surface <namespace>
   (<address>), which still had the keyboard to itself".
   -> verify by step 6's tests 1–7.

4. **`src/ai_mirror/cli.py`**: the `input` parser gains
   `p.add_argument('--window', help='address of the window or surface
   (layers) to type into; from `windows`')`. It flows through the existing
   `api.run(op, args)`.
   -> verify by test 8.

5. **Words.** `mcp.py`: the `windows` description says "List windows, and
   layer surfaces (menus, panels, launchers) under layers". The `input`
   description says `window` may be a layer's address. `gotchas.md`: one
   entry, "Typing into a menu, panel or launcher: open it, call windows,
   pass the layer's address (under layers) as window. It is refused while
   another surface is open at the same level or above". The `api.py:100`
   refusal text also mentions layers.
   -> verify by `index` showing the gotcha and by reading.

6. **`tests/test_layer_typing.py`**, in the style of
   `test_verified_input.py` (the same `Base`, `FakeHelper`, `grant`;
   `host.ctl` stubbed by argv):
   1. layer mapped, no window focused, alone at its level → sent; the
      result names it;
   2. a window focused → refused, nothing sent;
   3. another layer at the same level; another at a higher level → both
      refused, naming it;
   4. the address not among layers or clients → refused;
   5. `layers -j` raising → `unavailable`;
   6. a second overlay appearing between lines → the rest not sent;
   7. a client address → the #24 path (all of `test_verified_input.py`
      still passes unchanged);
   8. CLI `input --window 0x… '[{"type":"key","keys":["J"]}]'` → `api.run`
      receives `window`.
   -> verify by `python3 -m unittest discover -s tests -v` passing, run on
   razer.

7. **On razer**, after `nix build` and with the dev build run from the
   repo (not the installed service):
   - open nixarchy-pkg's panel; `ai-mirror windows` lists
     `nixarchy-pkg-menu` under `layers`;
   - with control granted by the person at razer: `ai-mirror input
     --generation N --window <address> '[{"type":"key","keys":["J"]}]'`
     moves the panel's cursor;
   - `nix flake check`.
   -> verify by a screenshot before and after the key.

8. **PR** linking intent, spec and plan; `Closes #26`.

## Found while implementing

- **Step 3: dispatch on layers only, and let `_require_focus` decide the
  rest.** The planned "read client addresses and layers, refuse neither"
  broke #24's tests, which stub only `focused_address`, so the extra
  `host.windows()` hit a real hyprctl. Now a mapped layer goes to the layer
  guard and anything else to `_require_focus`, exactly as before. That is
  one call fewer, and still positive: an unmapped address can't be the
  focused window. A layer query that fails also falls to `_require_focus`,
  which refuses a surface target (focus is no window ≠ its address), so
  failing to ask never becomes permission. The separate "not a mapped window
  or surface" message is lost; #24's "focus is X, not W" says it instead.
- **Step 7: the keystroke itself is unverified.** Control was requested on
  razer at 16:09 and expired unanswered. Verified live: the dev build's
  `windows` lists `nixarchy-pkg-menu` under `layers`, alone at level 3, and
  `input --window` exists. The 14 unit tests cover the guard.

## Tests

    python3 -m unittest discover -s tests -v     # on razer
    nix flake check                              # on razer (unittest + plugin checks)

## Rollback

`git revert` the implementation commit. The `windows` op's added key is
the only interface change, and it's additive; callers that ignore
`layers` see today's output.
