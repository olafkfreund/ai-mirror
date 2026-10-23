---
status: approved
issue: 65
intent: intent/2026-10-23-65-background-a11y-act.md
---

# Spec: a11y_act can be trusted to act without taking the human's cursor

## Design

Four changes, plus one measurement that informs the second and the docs.

### 1. Measure first (no code)

Before changing `click`, record what the applications on this machine actually
do. Under a normal grant, on a scratch workspace, one simple window each of
whatever is installed among GTK3, GTK4, Qt, Firefox and Chromium (launched with
`--force-renderer-accessibility` and a scratch `--user-data-dir`):

- the action names each button, checkbox, entry and link offers (`a11y-find`);
- for `click`, one named action, `set_text` and `focus`, with a *different*
  window focused: `hyprctl cursorpos`, `hyprctl activewindow -j` and the
  focused AT-SPI node before and after.

The result is a table of measured examples per application, not a rule per
toolkit, added to `src/ai_mirror/gotchas.md` under "Accessibility trees are
per-application". It decides whether `doDefault` (or another name) joins the
click list in change 2.

### 2. `click` runs a click or refuses; refusals are errors

`src/ai_mirror/a11y.py:384-388`:

- `wanted` for `click` is `('click', 'press', 'activate', 'jump')` plus every
  name the measurement found as a default click (expected: `doDefault`).
- The index-0 fallback goes. No match raises
  `unsupported: element actions are [...]` -- the existing message -- so the
  caller can name one.
- `do_action`'s boolean is checked like `grab_focus` and `set_text_contents`
  already are: `False` raises `unavailable: the application refused <name>`.

### 3. The guard, and the trap around it

One seam in `a11y.py`, the innermost call a test can stub:

```python
def _write(seam: str, call):
    guard.check(f'a11y.act {seam}', 'a11y._write')
    return call()
```

`grab_focus`, `set_text_contents` and `do_action` each go through it. `act()`'s
`except Exception` (`a11y.py:391`) gets an `except guard.Blocked: raise` ahead
of it, so a guard trip reaches the test with its own message instead of
becoming `unavailable`. (`guard.Blocked` is not a `RuntimeError` so that
`run_batch` does not bury it, `guard.py:20-24`; the same burying would happen
here through the broader `except Exception`.)

`_write` is called only from `act()`'s body, never from inside a
`wait.poll` probe: `poll` catches every exception and reports it as
`unavailable` (`wait.py:164`), which would swallow `Blocked` too. The probes in
change 4 only read, and reads are unguarded by design.

Existing tests that drive `act()` with a fake accessible past the point of
writing (none do today; `tests/test_reporting_truth.py:290` stops before it)
stub `a11y._write`.

### 4. Read back what can be read back

`act()` returns what it could see, without a second meaning for `ok`:

| Action | Check after | `verified` |
|---|---|---|
| `set_text` | Text interface reads back the written string (`get_text(0, -1)` compared in full) | `true`, or `not_confirmed` error |
| `focus` | `focused` in the node's states | `true`, or `not_confirmed` error |
| `click` / named | node states before and after; the node may be gone | `null`, with a note: "invoked; the effect is not visible to accessibility -- observe before reporting it" |

Checks poll with `wait.poll` for up to 1 s (`timeout` overridable as on
`window`), re-resolving the node id each probe. A child-index id can come to
mean a different control when the tree changes, so each probe also compares the
node's role with the role read before acting; a node that no longer resolves,
or resolves to a different role, is `after: null`. For `set_text` and `focus`
that is `not_confirmed` (the thing to check is gone); for a named action it is
reported, not an error -- a click that closes its dialog is normal.

`set_text` compares the complete text, but never returns it: `details` carries
the first 120 characters of the read-back and its length, the same cap `_node`
uses (`a11y.py:135`), so a mismatch cannot dump a whole document. The result gains `states_before`,
`states_after`, `verified`, `waited_ms`. A toggle or expand action is not
judged right or wrong -- the caller sees the states and decides; deciding for
it would mean guessing which direction it wanted.

### 5. Generation is required, and handed out with every observation

- `src/ai_mirror/api.py:255`: `a11y_act`, `window` and `launch` use
  `_generation(args)` -- the same function `input` uses -- instead of
  defaulting to the current state. Clipboard `write` by an agent
  (`api.py:224`) does the same. A human's CLI clipboard write stays ungated,
  as now.
- `_generation`'s message names where to get one: "generation is required --
  from status, windows, a11y_find, a11y_tree or a screenshot frame".
- `windows`, `a11y_tree` and `a11y_find` return `generation`, read from the
  state file **before** the walk starts. If the grant changes during the walk,
  the ids carry the old generation, and acting on them fails with
  `stale_generation` -- which is the right answer, with no extra check.
- `src/ai_mirror/mcp.py`: `generation: INT`, required, on `a11y_act`,
  `window`, `launch`; `clipboard` takes it optionally (required only for
  `write`, checked in `api`).
- `src/ai_mirror/cli.py`: `--generation` (required) on `a11y-act`, `window`,
  `launch`; `--expect` on `a11y-act` taking JSON `{"role": ..., "name": ...}`.
  The CLI clipboard write is the human's, so it takes no generation.
- Callers updated: `tests/smoke.py:42,44` (`launch`, `window`), `:56` (agent
  clipboard write), `:69` (cleanup `window close`, which must use the
  generation of the grant taken at `:67`, not the original one);
  `tests/test_invariants.py:348,352` (agent clipboard write; the test must
  still assert `DEVNULL`); `demo/demo.sh` (`launch`, `window`, `a11y-act`
  lines; the script already holds `$G`).

### 6. Words

- `a11y_act`'s MCP description: `focus` takes keyboard focus; `set_text` and
  named actions do not move the pointer; which ones activate a window is listed
  in `index` (from `gotchas.md`).
- `docs/usage.md`: generation on the four operations, `--expect`, the new
  result fields.

## Alternatives rejected

- **Guard each gi call where it stands.** Three copies of the same check, and
  a test that stubs one call still has to know the other two. One seam is the
  pattern `api._spawn` already uses.
- **Keep the index-0 fallback but report which action ran.** The action has
  already happened by then; telling the caller afterwards that it opened a
  context menu instead of clicking does not undo it.
- **Judge toggles (`checked` must flip).** An agent may want it off and find it
  on; the tool cannot know. Report states, let the caller judge.
- **Accept an omitted generation with a warning for one release.** Rejected in
  the intent (question 1): the caller that omits it is exactly the one acting
  on a stale view, and `input` already set the precedent.
- **A per-node token instead of generation + `expect`.** Stronger, but a new
  concept in every result for a problem `expect` already covers within a grant.

## Risks

- **Breaking change** for any external script calling `window`, `launch`,
  `a11y-act` or agent clipboard writes without a generation. The error says
  what to pass. Release notes must say so (next minor release).
- **Removing the fallback may stop some Chromium clicks** if the measurement
  misses a default action name. Mitigation: the refusal lists the names, so the
  caller can pass one; the measurement is done first precisely for this.
- **Read-back can be wrong where the app normalises text** (trims, reformats a
  number). That surfaces as `not_confirmed`, the honest answer, with the
  read-back text in `details` so the caller can see why.
- **Measurement drives the live desktop.** Done only under a grant the human
  gives, on a scratch workspace, with scratch browser profiles.

## Verification

- `python3 -m unittest discover -s tests -v` green, with new tests:
  - with the guard armed and `resolve` stubbed to a fake accessible,
    `act(..., 'click')` raises `guard.Blocked` (not `MirrorError`);
  - `click` on a node offering only `['showContextMenu']` raises `unsupported`
    and calls nothing; on `['doDefault']` it invokes `doDefault`;
  - `do_action` returning `False` raises `unavailable`;
  - `set_text` whose read-back differs raises `not_confirmed`, with at most
    120 characters of it in `details`;
  - a probe whose re-resolved node has a different role reports `after: null`;
  - `a11y_act`, `window`, `launch` and agent clipboard `write` without
    `generation` raise the new message; with a stale one, `stale_generation`;
  - `windows`, `a11y_tree`, `a11y_find` results carry `generation`, read before
    the walk (stub the walk to bump the state mid-way; the result keeps the old
    value).
- `nix flake check` green.
- Live, under a grant: the measurement table exists in `gotchas.md`;
  `tests/smoke.py` passes with the updated calls; `demo/demo.sh` runs.
