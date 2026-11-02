---
status: approved
issue: 97
intent: intent/2026-11-02-97-surface-events.md
---

# Spec: the surface check sees a surface that left and came back between checks

## Design

Two small changes, one in each module; no new tool, argument or dependency.

### 1. The recorder keeps the namespaces closed during this grant (`src/ai_mirror/events.py`)

- `Recorder` gets `closed: set[str]`, emptied by `clear()` along with the ring,
  so it always belongs to `Recorder.generation`.
- `feed()`, on a recorded `closelayer` line, adds its data (the namespace,
  uncapped) to `closed` in the same place it maintains `classes`.
- `Recorder.closed_layers(generation) -> set[str]`: a copy under the lock when
  `generation == self.generation`, else an empty set.

A set, not the ring: the ring holds 512 events and drops the oldest, but a
departure must not be lost to overflow. The set is bounded by the number of
distinct namespaces on the desktop. The reader thread still writes no state
file (#95 review); it only adds to memory the main thread reads.

### 2. The check also counts departures from events (`src/ai_mirror/control.py`, `_furniture`)

Today `gone = set(baseline) - present`. It becomes

```python
gone = (set(baseline) - present) | (set(baseline) & _closed_since_grant(state.get('generation')))
```

and the existing branch writes `baseline_layers`/`baseline_departed` under the
lock with the generation re-check (approved decision 2). The rest of
`_refuse_new_surfaces` is untouched: a baseline namespace that closed and is
mapped again is "new", and because it is in `departed`, the refusal names it
"went away and came back since control was granted".

`_closed_since_grant` imports `events` inside the function (events imports
control, so a module-level import would be a cycle) and returns
`events.RECORDER.closed_layers(generation)`.

### Why this is never weaker

Events only ever *add* to `gone`; sampling still runs on every check. So:

- CLI process: the recorder never recorded (`generation is None`) → empty set →
  exactly today's behaviour. No "is the record complete" test is needed, because
  an incomplete record (disconnected reader, gap, overflow, late start) can only
  miss departures that sampling would also have to catch, as it does today.
- A `closelayer` from before the grant that is delivered late would count as a
  departure: stricter, never weaker.
- Generation mismatch (grant changed between the recorder's last line and the
  check) → empty set → today's behaviour.

### Docs

`gotchas.md`, the "Typing at a window" paragraph: through MCP, a baseline surface
that closes is seen leaving even if it is back by the next check; through the
CLI, or if the reader was disconnected when it closed, a quick leave-and-return
still goes unseen. The shell-restart paragraph: through MCP a restart is now
seen, so window-addressed input is refused until control is re-taken (decision 1).

## Alternatives rejected

- **Scan the ring at check time** for `closelayer` events. Overflow (512) would
  silently drop a departure; the set has no such limit.
- **Have the reader thread write `baseline_departed`.** State belongs to the
  main thread (#95 review); a thread write races `_write` and grant changes.
- **Require the record to cover the whole grant before using it.** Unnecessary:
  the union can only make the check stricter, so a partial record is still safe
  to use, and the test would be machinery for nothing.
- **Exempt shell namespaces (bar, background) from event departures.** Rejected
  by decision 1: admitting whatever returns reopens the hole for anything that
  can be made to flicker.

## Risks

- **More refusals on p620 through MCP.** A shell restart, or a monitor change
  that unmaps one of two same-namespace bars, now refuses window-addressed input
  until control is re-taken. Accepted (decision 1). The refusal names the surface,
  and `layer`-addressed input is unaffected.
- **Namespace granularity.** Departures are by namespace, as the baseline is; one
  instance closing marks every instance of that namespace departed. Stricter only.
- **Import cycle.** Avoided by the function-level import; a test imports
  `control` alone and runs the check.

## Verification

- Unit tests (`python3 -m unittest discover -s tests`), all with `guard.arm()`:
  - `feed` adds a `closelayer` namespace to `closed` only while held; `clear`
    empties it; `closed_layers` with another generation is empty.
  - `_furniture` with a baseline namespace still mapped but in `closed` drops it
    from `still`, adds it to `departed`, and writes both to the state file.
  - `_refuse_new_surfaces` then raises `wrong_target` with "went away and came back".
  - The same scenario with an empty recorder (the CLI path) does not refuse —
    today's behaviour.
  - A recorder at another generation is ignored.
- `nix flake check` and `nix build .#ai-mirror`.
- Live on p620 through the checkout's MCP server: open the Quickshell audio panel
  (level ≥ 2) before asking for control, so it is in the baseline; after the
  grant, close and reopen it with `qs ipc` with no check in between; a
  window-addressed `input` is refused with "went away and came back". Before this
  change the same sequence is let through. The refused input sends nothing.
