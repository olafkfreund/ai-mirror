---
status: approved
issue: 97
spec: spec/2026-11-02-97-surface-events.md
---

# Plan: the surface check sees a surface that left and came back between checks

## Approved decisions (self-contained)

- Through MCP, a `closelayer` of a baseline namespace seen since the grant drops
  it from the furniture, as if a check had sampled it gone. If it is mapped again
  at the next window-addressed check, the refusal says "went away and came back".
- Events only **add** departures; sampling still runs on every check. CLI, a
  disconnected reader, a gap, an overflowed ring or a recorder at another
  generation all give an empty or partial set → today's behaviour. No
  completeness test.
- Departures live in a per-grant `set` on the recorder, not the 512-event ring
  (overflow must not lose one). The reader thread writes no state file; the main
  thread reads the set at check time and writes `baseline_layers` /
  `baseline_departed` through the existing locked, generation-checked write.
- No namespace is exempt: a shell restart seen in events refuses window-addressed
  input until control is re-taken.
- No new tool, argument or dependency; `events` stays MCP-only.

## Steps

1. `src/ai_mirror/events.py`, `Recorder` (lines 59–95) and `feed` (108–127):
   - `__init__`: `self.closed: set = set()`; `clear()`: `self.closed = set()`
     inside its lock.
   - New method `closed_layers(self, generation) -> set`: under the lock, return
     `set(self.closed)` if `generation is not None and generation == self.generation`,
     else `set()`.
   - `feed`: next to the `closewindow` branch, `elif name == 'closelayer': rec.closed.add(data)`
     (the parsed, uncapped data is the namespace).
   → verify `python3 -m unittest discover -s tests` (`tests` is not a package, so `tests.test_events` does not import from the root).
   Traps: `rec.classes` is mutated without the lock today (reader thread only);
   `closed` is read from the main thread, so the add goes under `rec.lock`.

2. `src/ai_mirror/control.py`, `_furniture` (lines 686–717):
   - Add above it
     ```python
     def _closed_since_grant(generation) -> set:
         from . import events  # here, not at the top: events imports control
         return events.RECORDER.closed_layers(generation)
     ```
   - In `_furniture`: `closed = _closed_since_grant(state.get('generation'))`;
     `still = [name for name in baseline if name in present and name not in closed]`;
     `gone = set(baseline) - set(still)`. Everything else (the `len` test, the
     locked re-read, `_forget_departed`, the write) unchanged.
   - Docstring: one sentence that departures also come from the MCP server's
     event record (#97), which can only add to them.
   → verify `python3 -m unittest discover -s tests`.
   Traps: never weaker — an exception from the recorder must not skip the
   sampled check; `closed_layers` only copies a set under a lock, so no try is
   added (an exception there would surface as a tool error, refusing, not
   passing). Do not touch `_refuse_new_surfaces`.

3. Tests:
   - `tests/test_events.py`, class `Recording`: `closelayer` while held adds to
     `closed`; while not held it does not; `clear(2)` empties it;
     `closed_layers(other generation)` and `closed_layers(None)` are empty.
   - `tests/test_reporting_truth.py`, class `ContinuousPresence`, using its
     `_grant_with` / `_check_with` helpers and `patch.object(events, 'RECORDER', rec)`
     with `rec.clear(generation); rec.closed.add('omarchy-audio')`:
     a. baseline `['omarchy-background', 'omarchy-bar', 'omarchy-audio']`, audio
        still mapped, in `closed` → `_check_with` returns `wrong_target` whose
        message contains "went away and came back"; state has `omarchy-audio` in
        `baseline_departed` and not in `baseline_layers`.
     b. same without the recorder (fresh `events.Recorder()`, never cleared — the
        CLI path) → `None`, baseline unchanged.
     c. recorder cleared at `generation + 1` → `None`.
     d. `control` path imports cleanly: `_closed_since_grant(None) == set()`.
   → verify `python3 -m unittest discover -s tests` (all pass, count up by ≥ 8).
   Traps: `Base.setUp` arms the guard; nothing here needs disarming.

4. `src/ai_mirror/gotchas.md`, lines 207–218 ("Typing at a *window*" and the
   shell-restart paragraph): replace "Checks run only on window-addressed calls,
   so a quick leave-and-return goes unseen" with: through MCP, a baseline surface
   seen closing in Hyprland's events counts as gone even if it is back by the
   next check; through the CLI, or while the event reader was disconnected, a
   quick leave-and-return still goes unseen. Restart paragraph: through MCP a
   restart is now seen, so window-addressed input is refused until control is
   re-taken.
   → verify `nix flake check` (also runs the tests) and `nix build .#ai-mirror`.

5. Live check on p620 (I run it, you answer the dialog), checkout MCP server:
   open the Quickshell audio panel (`qs ipc --pid <shell> call omarchy.audio open`),
   check it is level ≥ 2 in `hyprctl layers -j`; ask for control; after the grant
   close and reopen it with `qs ipc`, no tool call between; `input` with a
   `window` address and one harmless key → expect `wrong_target`, "went away and
   came back", nothing sent. Close the panel, `control off`. Record the result in
   this plan.

## Implementation

Steps 1–4 edit four files, so they go to the `coder` agent (one agent, steps sent
with `SendMessage`); I commit each step and review the diff with a fresh Opus
agent given only this plan and `git diff master`.

## Tests

`python3 -m unittest discover -s tests` all pass; `nix flake check` passes;
step 5 refuses as described.

## Rollback

Revert the merge commit in ai-mirror and bump nixarchy's ai-mirror input back;
the state file format is unchanged, so no migration.

## Deviations during implementation

- Step 1 (coder): no code deviation. Verify command corrected: `tests` is not a
  package, so the discover form is used. 378 tests OK.
- Step 2 (coder): no deviation. 378 tests OK.
- Step 3 (coder): plan's recording cases merged into two tests, plus one extra (closed and still gone → only departed). 385 tests OK (+7, plan said ≥ 8).
- Step 4 (coder): no deviation. nix flake check passed, nix build .#ai-mirror OK.
