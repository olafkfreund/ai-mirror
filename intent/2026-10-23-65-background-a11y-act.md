---
status: draft
issue: 65
author: olafkfreund
---

# Intent: a11y_act can be trusted to act without taking the human's cursor

## Problem

`a11y_act` is the one route that can work inside an application without moving
the human's pointer: it asks the application's accessibility interface to do
the thing, instead of sending the virtual pointer and keyboard to it. That makes
it the answer to "let the agent work while I keep my cursor", which the Cua
seat plugin solves at the cost of an Arch-only compositor module. But today it
cannot be trusted for that, for four reasons:

- **The tests can reach the desktop through it.** `grab_focus`,
  `set_text_contents` and `do_action` (`src/ai_mirror/a11y.py:364,379,388`)
  have no `guard.check`. AGENTS.md: "Tests cannot reach the desktop." A test
  that forgets one stub clicks something on the human's live session. And a
  guard put naively inside `act()` would be swallowed: its `except Exception`
  (`a11y.py:389`) turns `guard.Blocked` into an ordinary `unavailable` error,
  burying the message that says what to stub.
- **`click` can do something else.** When an element offers none of
  `click`, `press`, `activate` or `jump`, it runs whatever action is first
  (`a11y.py:385`) -- a menu, a toggle, an author-defined action. Chromium may
  call its default `doDefault`, which is not in the list, and so may depend on
  that fallback today.
- **It reports `ok` when an application refused the action.** `do_action`'s
  true/false is thrown away (`a11y.py:388`); `grab_focus` and
  `set_text_contents` already check theirs. And for every action, nothing looks
  at the element afterwards, so a delivered action reads as a done one. This is
  #8 again, as #24 was for `input` and #53 for `window`.
- **A grant that was taken back still works.** `api.py:255` fills a missing
  `generation` with the current one, and neither the MCP schema nor the CLI
  lets `a11y_act` pass one, so `stale_generation` can never fire. An agent
  stopped and later re-granted acts on node ids it read under the old grant.
  The CLI cannot pass `expect` either, so a CLI caller has no stale-node check.
  `window`, `launch` and clipboard `write` (`api.py:223`) have the same shape.
  Generation does not replace `expect`: within one grant a child-index id can
  still come to mean a different control.

And one thing nobody knows: **which actions take the human's keyboard focus or
activate a window** on this Hyprland. `focus` does by definition; the
Chromium text route (`focus`, then `input`) does by design. Whether a GTK, Qt,
Firefox or Chromium `click` raises its window has not been measured, so
"without taking your cursor" is currently a guess.

## Proposed outcome

- No AT-SPI write in `a11y_act` runs while the test guard is armed.
- `click` runs a click-like action or refuses, naming the actions the element
  does offer. Chromium's default action still works.
- `a11y_act` returns an error when the application refuses the action, and
  says whether it could see the effect (`verified`) or could not tell, so an
  agent never reads "delivered" as "done".
- With the guard armed, an unstubbed AT-SPI write fails the test with the
  guard's own message, as AGENTS.md requires -- not merely "does not reach the
  desktop".
- `a11y_act`, `window`, `launch` and clipboard `write` fail with
  `stale_generation` when the grant their caller observed under has been
  replaced, and the CLI can pass `expect`.
- A written measurement on this machine of whether `click`, a named action,
  `set_text` and `focus` move the pointer, change the active window, or change
  keyboard focus -- recorded as measured examples per application, not as a
  rule for a whole toolkit, since each element supplies its own actions. It
  goes into `gotchas.md`, and the tool description says which actions are
  known to take focus.

## Affected users and systems

- Agents using `a11y_act`, `window`, `launch` or clipboard `write` over MCP or
  the CLI: a new failure mode (`stale_generation`, refused actions).
- In-repo callers that omit `generation`: `tests/smoke.py:44` (`window`),
  `demo/demo.sh:34` (`a11y-act`).
- `src/ai_mirror/a11y.py`, `api.py`, `mcp.py` (schemas), `cli.py`,
  `gotchas.md`, `docs/usage.md`, tests.
- No change to the confirm dialog, the helper, the plugin or `ai-mirror-input`.

## Constraints

- Generation + owner still gate every mutating operation; this only makes the
  generation check real for four operations.
- Put the guard on the innermost real call, the one a test stubs.
- Reads stay unguarded (`a11y_tree`, `a11y_find`, `index` must keep working).
- Existing callers that pass no `generation` must get a clear message saying
  what to pass, not a bare refusal (#24's lesson: a model told only "no"
  retries).
- The measurement drives the real desktop, so it runs under a normal grant
  from the human, on a scratch workspace, and changes no code.
- Stdlib only, no new dependencies.

## Open questions

1. Require `generation` on `a11y_act`/`window`/`launch` (breaking for callers
   that omit it), or accept an omitted one with a warning for one release?
   Proposed: require it, as `input` does, and return it from `a11y_tree`,
   `a11y_find` and `windows` so the caller always has one to hand back. The
   returned generation must belong to the observation: read before the walk,
   and if the grant changed during it, say so rather than label old ids with
   the new grant.
2. Should `focus` stay in `a11y_act` when the goal is background work?
   Proposed: keep it -- it is needed for the Chromium text route -- and mark it
   in the tool description as taking keyboard focus, even though it never moves
   the pointer.
3. Scope of the measurement: which apps? Proposed: whatever of GTK3, GTK4,
   Qt, Firefox and Chromium (with `--force-renderer-accessibility`) is
   installed here, one simple window each.
