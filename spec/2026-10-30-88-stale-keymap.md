---
status: approved
issue: 88
intent: intent/2026-10-30-88-stale-keymap.md
---

# Spec: typed text and the keys after it reach the window with a stale keymap

## Design

**The helper's persistent keyboard keeps one keymap for its whole life, and
each typing round gets a throwaway keyboard of its own.**

Today `T` (`src/ai_mirror_input/ai_mirror_input.c`, the `op == 'T'` branch)
uploads a throwaway keymap to the persistent keyboard `kbd`, sends the keys,
then uploads the default map again. Hyprland misses those changes (intent),
so the client keeps an old map. After this change:

1. `kbd` gets the default `us` map once at startup (as now, line 446) and
   never another one. Every `K` line stays on `kbd`, unchanged.
2. For each round of at most `N_TYPE_CODES` distinct codepoints, `T`:
   - creates a keyboard `tk` with
     `zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(kbd_mgr, seat)`;
   - uploads the round's type map to `tk`, sets `tk`'s modifiers to 0, round
     trip;
   - sends the press and release of each key on `tk`, round trip;
   - destroys `tk` with `zwp_virtual_keyboard_v1_destroy`, round trip.
3. After the last round, `send_modifiers()` on `kbd` (as now). The
   `send_keymap(default_map)` restores go, both the one after the loop and
   the one on the `build_type_map` failure path, which now just answers
   `ERR keymap failed` (no keymap was changed, so there is nothing to undo).
4. `send_keymap` takes the keyboard to send to, so it serves both.
5. The header comment (lines 17-19) says each typing round uses its own
   keyboard, and why (#88).

Why it works, from Hyprland `3633316`: a new keyboard becomes the active one
when it is created (`InputManager.cpp:1179`), so the client receives the
type map as a new keymap; when it is destroyed, the most recent remaining
keyboard becomes active again (`InputManager.cpp:1529-1535`), and its
unchanged default map is resent. No keyboard ever changes its keymap after
the first upload, which is the case Hyprland gets wrong.

Python is untouched: `input.py` still emits `T` and `K` lines, `run_batch`
still acks each line, and `C` still releases only `kbd` and the pointer,
which is all that can be held: `tk` never holds a key past its round.

### Measured before choosing

The prototype of this design, in a `nixarchy-desktop` microvm on Hyprland
`3633316`, driven through MCP with the helper swapped in by a copy of the
packaged wrapper. Five checks per terminal (three rounds of `type` +
`RETURN`, a newline inside the text, two `type` actions then `RETURN` in its
own call), plus one non-ASCII file name. A check passes if the typed `touch`
creates its file on the host share:

| Helper | foot | alacritty | kitty | `é€` |
| --- | --- | --- | --- | --- |
| 3.1.0 (today) | 0/5 | 0/5 | 0/5 | 0/3 |
| this design | 5/5 | 5/5 | 5/5 | 3/3 |

## Alternatives rejected

- **Type ASCII with real key codes from the default map, keep the keymap
  switch for the rest.** Prototyped: foot 3/5, alacritty 5/5, kitty 5/5, and
  every non-ASCII round failed, because those still switch the keymap.
- **Restart the helper for every call.** Measured with the CLI, which does
  that: the text is right, the `RETURN` after it is still lost, because one
  keyboard still uploads three keymaps.
- **Paste through the clipboard.** It overwrites the user's clipboard and
  depends on each application's paste binding.
- **Wait for a Hyprland fix.** We will report it (intent, question 1), but
  agents type on this Hyprland now.

## Risks

- **A keyboard per round is visible to Hyprland.** Each one runs
  `newKeyboard` and `destroyKeyboard`: Hyprland logs it and emits
  `activelayout` on its event socket. `wtype` does the same on every call.
  Anything watching device changes sees one add and one remove per typing
  round (16 distinct characters per round). Nothing in ai-mirror or
  Omarchy's bar is known to act on them.
- **Which keyboard is active afterwards.** After `tk` goes, Hyprland makes
  the most recently added remaining keyboard active. That is `kbd`, as it is
  today, since the helper starts after the human's keyboards. Unchanged.
- **Hyprland still compares against a dangling `string_view`** after `tk` is
  destroyed. A type map is about 1.5 KB and the default map about 35 KB, so
  the lengths differ and the comparison never reads the freed bytes. This is
  Hyprland's undefined behaviour, not ours, and goes in the upstream report.
- **The real desktop is not measured yet.** Same Hyprland and helper, so the
  same bug is expected; verification step 4 checks it.
- **Hosts:** every host that runs ai-mirror, after a lock bump. No secrets,
  no service changes.

## Verification

1. `nix build .#ai-mirror-input` and `nix flake check` pass, and
   `python3 -m unittest discover -s tests` passes unchanged.
2. The prototype matrix above, rerun with the committed helper on a freshly
   booted `nixarchy-desktop` microvm: 5/5 in foot, alacritty and kitty, and
   3/3 for `é€`.
3. In the same VM, `wev` shows the type map arrive before each round's keys
   and the default map before the following `RETURN`.
4. On the real desktop, with the owner granting control once: in a foot
   window on an empty workspace, `type` `touch /tmp/ai-mirror-88-<i>` +
   `RETURN`, three rounds, three files.
5. After it is measured, report the `m_lastKeymap` aliasing to
   hyprwm/Hyprland with the evidence from steps 2-3.
