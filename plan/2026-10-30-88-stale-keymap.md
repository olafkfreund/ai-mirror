---
status: approved
issue: 88
spec: spec/2026-10-30-88-stale-keymap.md
---

# Plan: typed text and the keys after it reach the window with a stale keymap

> **Correction, found while implementing (2026-10-30).** The intent and spec
> blame a `std::string_view` in `Seat.cpp:379`. That is wrong:
> `m_lastKeymap` is a `std::string` (`Seat.hpp:137`). A second explanation
> (keymap changes forwarded only from the main keyboard, which key events
> do not change) is wrong too: key and modifier events make their keyboard
> main (`InputManager.cpp:1743`, `:1784`). The mechanism inside Hyprland is
> not known. What is measured stands: foot's own `WAYLAND_DEBUG` trace shows
> the stock helper's switch back to the default map never arriving before
> `RETURN`, and the design below fixes every case measured. The design is
> unchanged.
>
> **Deviation, from review (2026-10-30), step 1.** `send_keymap` returns
> whether it uploaded. If it did not, `T` destroys `tk`, drops the map and
> answers `ERR keymap failed`: a keyboard without a keymap would be a
> protocol error on its next request and end the helper as "compositor
> gone".

Approved decisions, carried over from the spec:

- The helper's persistent keyboard `kbd` gets the default `us` map once at
  startup and never another. `K` lines stay on `kbd`.
- Each `T` round (at most `N_TYPE_CODES` distinct codepoints) creates a
  throwaway keyboard `tk`, uploads the round's type map to it once, sets its
  modifiers to 0, sends the keys, destroys it, with a round trip after each
  of those three. No keymap is restored on `kbd`; `send_modifiers()` on
  `kbd` still ends the `T` line.
- Python is untouched. `C` still releases `kbd` and the pointer only.
- Rejected: real key codes from the default map (foot 3/5, non-ASCII 0/3),
  a helper per call (`RETURN` still lost), clipboard paste, waiting for
  Hyprland.
- Verification includes one real-desktop check with the owner granting
  control, then an upstream Hyprland report.

## Steps

1. `src/ai_mirror_input/ai_mirror_input.c`, one commit:
   - lines 72-88: `send_keymap(struct xkb_keymap *map)` becomes
     `send_keymap(struct zwp_virtual_keyboard_v1 *to, struct xkb_keymap *map)`
     and uploads to `to`; the startup call at line 446 passes `kbd`.
   - lines 355-380 (`op == 'T'`): replace the per-round
     `send_keymap(map)` / keys / restore with: create `tk` from
     `kbd_mgr` and `seat`; `send_keymap(tk, map)`;
     `zwp_virtual_keyboard_v1_modifiers(tk, 0, 0, 0, 0)`; round trip; the
     press and release of each key on `tk`; flush and round trip;
     `zwp_virtual_keyboard_v1_destroy(tk)`; round trip. On
     `build_type_map` failure, print `ERR keymap failed` and return, with no
     `send_keymap` (line 359 goes). After the loop, delete
     `send_keymap(default_map)` (line 379) and keep `send_modifiers()`, the
     flush, the round trip and `OK`.
   - lines 17-19, header: each typing round uploads its throwaway keymap to
     a throwaway keyboard, because Hyprland can miss a keymap change on an
     existing keyboard (#88); the persistent keyboard keeps the default map.

   → verify: `nix build .#ai-mirror-input`, `nix flake check`,
   `python3 -m unittest discover -s tests` all pass.

   Traps: `roundtrip_or_die` stays on every path, so a dead compositor
   still answers `ERR compositor gone`. Every `T` path still prints exactly
   one ack line, or `run_batch` hangs. `tk` must not outlive its round:
   destroy it before the next round's `tk` is made.

2. Measure, no file edits:
   - Fresh `nixarchy-desktop` microvm (runner from nixarchy main with
     #1516, or edge), MCP served through a copy of the packaged `ai-mirror`
     wrapper whose `AI_MIRROR_HELPER` points at step 1's build (the wrapper
     overrides the environment variable). Scratchpad probe
     `nd-proto3.py`: foot, alacritty and kitty, five checks each, plus `é€`.
     Expect 5/5, 5/5, 5/5 and 3/3.
   - `wev` in the same VM (`WAYLAND_DEBUG=client foot` works too): the type
     map arrives before each round's keys, the default map before the
     `RETURN`.
   - Real desktop, after asking the owner: control is granted through the
     dialog, then in a foot window on an empty workspace `type`
     `touch /tmp/ai-mirror-88-<i>` + `RETURN`, three rounds, three files.
     Same helper swap through a wrapper copy.
   - Then report the `m_lastKeymap` aliasing to hyprwm/Hyprland with the
     step 2 evidence.

   → record the results in the PR.

## Tests

- `python3 -m unittest discover -s tests -v`: unchanged and passing
  (`input.py` still emits the same lines; `tests/test_invariants.py:274`
  covers that).
- `nix flake check`: passes.
- The step 2 matrix is the behavioural test. A C test against a live
  compositor would break the rule that tests cannot reach the desktop.

## Rollback

Revert step 1's commit. The helper goes back to switching `kbd`'s keymap;
nothing else depends on the change, and nothing is persisted.
