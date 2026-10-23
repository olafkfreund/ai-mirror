---
status: draft
issue: 70
author: olafkfreund
---

# Intent: set values and select items without the pointer

## Problem

#65 made `a11y_act` the route for working in an application without taking
the human's cursor: it is guarded, `click` only clicks, it reads back what it
did, and it needs the grant's generation (PR #67). Measured on this host, no
`a11y_act` action moved the pointer or changed the active window.

But it can only click, focus, set text, or run a named action. Two common
kinds of control are out of its reach:

- **Ranged controls** -- sliders, spin buttons, volume and brightness,
  zoom. There is no way to read their value or set one. An agent drags with
  the pointer or presses arrow keys into the focused window, both of which
  take what the human is using.
- **Choosers** -- lists, combo boxes, tab bars, tree rows. There is no way to
  say "select this item". Clicking an item may work, but for a combo box it
  opens a popup (a new surface over the human's work) and for a list it can
  also move keyboard focus.

`_node` (`src/ai_mirror/a11y.py:127-146`) reports roles, names, states,
bounds, actions and text, but no value; `act()` has no value or selection
branch. AT-SPI has an interface for each: `Value` (current, minimum,
maximum, minimum increment; set current) and `Selection` (select or deselect
a child, which children are selected). Neither is used.

Deferred from #65's spec ("Out of scope (follow-up)").

## Proposed outcome

- `a11y_tree` and `a11y_find` show a ranged control's value and range, so an
  agent can read a slider without a screenshot.
- `a11y_act` can **set a value** on a ranged control and **select an item**
  in a chooser, with #65's guarantees: through the guarded `_write` seam,
  the grant's generation required, and read back afterwards (`verified` /
  `not_confirmed`), never a bare `ok`.
- A measured table, like #65's, of which installed applications expose
  `Value` and `Selection` on which controls, and whether using them changed
  the pointer, the active window or keyboard focus.

## Affected users and systems

- Agents using `a11y_tree`, `a11y_find`, `a11y_act` (MCP and CLI).
- `src/ai_mirror/a11y.py` (`_node`, `act`), `mcp.py` (schema and
  description), `cli.py`, `gotchas.md` (measured table), `docs/usage.md`,
  tests.
- Builds on PR #67; this branch is stacked on it until #67 merges.

## Constraints

- Every AT-SPI write goes through `a11y._write` (the guard), never around it.
- `a11y_act` keeps requiring `generation`; nothing here relaxes the gate.
- The privacy check in `resolve()` still runs before any write; a value or
  selection inside a withheld window is refused like any other action.
- Read-back follows #65: a write the application accepts but that cannot be
  confirmed is `not_confirmed`, and a read-back failure after a delivered
  write says it was delivered.
- Reads stay unguarded; `_node` reading a value must not slow the tree walk
  noticeably (one interface query per node, as `text` already does).
- The measurement drives the real desktop, so it runs under a grant from the
  confirm dialog, on a scratch workspace, and changes no code.
- Stdlib and PyGObject only.

## Open questions

1. **How is the item to select named?** Proposed: by the item's own node id
   (from `a11y_tree`/`a11y_find`), and `a11y_act` finds its parent's
   `Selection` and the item's index -- consistent with every other id in the
   tool, and the item's name and role can be checked with `expect`.
2. **Deselect and clear too, or select only?** Proposed: select and
   deselect (multi-select lists need both); no "clear all", which is the
   destructive one with the least use.
3. **Out-of-range values:** refuse before writing, or let the application
   clamp and report the read-back? Proposed: refuse values outside
   `[minimum, maximum]` before writing, naming the range -- the read-back
   would otherwise report `not_confirmed` for a value that was never valid.
4. **Measure first?** Proposed: yes, as #65's plan step 1, because this
   desktop's idle tree exposes almost nothing (40 nodes, Chrome without
   `--force-renderer-accessibility`), so which apps implement these
   interfaces is unknown until apps are launched under a grant.
