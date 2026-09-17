---
status: draft
issue: 3
author: olafkfreund
---

# Intent: A desktop index, so an agent stops rediscovering this host

## Problem

An agent granted desktop control begins every session knowing nothing about the
machine it is about to drive. It does not know which keybinding opens which
panel, which plugins are installed, which surfaces answer to the accessibility
API and which are keyboard-only, or which keys write to disk. It learns those
things by grepping configuration and poking at the user interface, and where it
guesses instead of checking, it guesses wrong.

This is not hypothetical. One screencast session on 2026-09-17 spent time on:

- guessing `SUPER+ALT+H` for the herdr menu, which changed the wallpaper. The
  real bindings — `SUPER+SHIFT+H`, `SUPER+H`, `SUPER+ALT+N`, `SUPER+ALT+A` —
  were in `~/.config/hypr/*.lua` throughout, each already carrying a
  human-readable label from `o.bind("KEYS", "Label", "command")`
- three failed attempts at Hyprland 0.56's Lua dispatch before finding
  `hl.dsp.focus({ ... })`
- measuring bar widget coordinates twice, by screenshot and neighbour-upscale,
  because nothing reports them
- hovering the bar, which expands the tray and shifts every widget, quietly
  invalidating coordinates measured seconds earlier
- a stray `Return` in the package panel writing `chrome.enable = true` into the
  nixarchy configuration, and a second queueing a removal of `azure-cli`. Both
  were real edits to files under the user's configuration. Neither was applied,
  both had to be noticed and reverted
- `herdr` refusing to start nested inside a herdr session
- closing shell panels with Escape, which a focused search field swallows, so
  panels stacked on top of one another

Two different problems hide in that list, and they need different answers.

About half is **state that already exists in local files** and was simply never
read. That is waste: the facts are present, cheap to parse, and stable.

The rest are **lessons no index can compute** — that hovering the bar expands
the tray, that `Return` on a boolean row edits a file, that herdr will not
nest. Nothing in the system states these. They were learned by causing them,
and unless they are written down they will be learned by causing them again.

A third of the cost was neither: the agent had `a11y_find` available and the
server's own instructions recommend it over screenshots, and it reached for
pixel coordinates anyway. An index cannot fix that, and this intent should not
pretend otherwise. It can only make the better path the obvious one.

## Proposed outcome

An agent starting a desktop task on this host can ask one question and receive,
in a single answer, the working knowledge it currently spends its first twenty
minutes reconstructing:

- every keybinding, with the human-readable label the configuration already
  attaches to it, so intent maps to key without grepping
- every QuickShell plugin, its identity, and how it is opened and navigated
- the bar layout, and which widgets are actually rendering
- installed applications and services as the system declares them
- the `omarchy-shell` IPC surface and the `omarchy-*` commands available
- Hyprland's dispatch form for the running version, and current monitor and
  workspace state
- for each surface, whether it exposes an accessibility tree or must be driven
  by keyboard — QuickShell exposes none, Electron and GTK expose full trees
- the accumulated gotchas: the things that bite, why, and what to do instead

Observable difference: the guesses above become lookups. A new agent does not
repeat the wallpaper incident, does not measure coordinates, and does not
discover the package panel's write behaviour by writing to the user's
configuration.

## What this does not fix

Named here because the measurements above invite a conclusion they do not
support: that knowing more makes an agent fail less, therefore an index is the
fix. It is *a* fix, for one of three causes.

**It does not fix acting blind.** The worst outcome in that session — a removal
of `azure-cli` written into the user's configuration — came from typing into a
filter that never took focus, which shifted the tab count, so a `Return`
intended for an option list landed on a package row. No prior knowledge
prevents that; only checking does. And checking is expensive: the shell answers
`Function not found` to `isOpen`, `visible`, `panels`, `activePanel`,
`listOpen`, `openPanels` and `status`, so "is this panel open, and which tab has
focus?" can only be answered by taking a screenshot and looking at it. Scripts
therefore skip verification and proceed on assumption. That gap belongs to
nixarchy's QuickShell plugins rather than to ai-mirror, and is tracked
separately as olafkfreund/nixarchy#749.

**It does not make the server faster.** ai-mirror returns in milliseconds. What
was slow was the agent: one model round trip per action. The cure for that was
batching — a single script drove ~40 actions and 28 narration steps with no
round trips at all — and it is already available to anyone who writes one. An
index lowers a per-session cost; batching lowers a per-action cost.

The honest ordering is that an index is the cheapest of the three and a
precondition for the second: you cannot write useful verification until you
know which states are worth asserting. It should not be sold as more than that.

## Affected users and systems

- **p620** and any other nixarchy host running the ai-mirror MCP server.
- **Any agent session with desktop control**, from any project directory — not
  only sessions working inside the ai-mirror repository. This matters: the
  knowledge is host-scoped, while `AGENTS.md` is repository-scoped, so the two
  do not currently reach the same audience.
- **Reads from** configuration owned by other projects: `~/.config/hypr`,
  `~/.config/omarchy`, `~/.config/nixarchy`, and the omarchy tree in the Nix
  store. ai-mirror would become a consumer of nixarchy's layout and would
  break when that layout changes.
- **The user**, who is the one who pays when an agent guesses: a changed
  wallpaper mid-recording, or an unrequested edit to system configuration.

## Constraints

- **Must not cache.** A stale index that states a keybinding with confidence is
  worse than no index. Every source is a small local file; regeneration is
  cheap and correctness is free.
- **Must not record pixel coordinates as durable fact.** They drift silently —
  the tray expands under a hovering cursor and everything moves. Coordinates
  were the largest single failure source in the session above.
- **Must not become a second source of truth.** It reports what the system
  says; it does not restate it, and where the two disagree the system wins.
- **Must degrade rather than fail.** A missing or renamed configuration file
  should shrink the answer, not error. A half-index still beats guessing.
- **Must respect the existing ownership gate.** Reading the host's shape is not
  controlling it, and the index must not become a way to learn about a machine
  the agent has not been given control of. Whether reading requires the gate is
  an open question below.
- **Contains personal data.** Application lists, workspace names, plugin sets
  and session titles describe the person using the machine. The screencast
  session surfaced exactly this class of content — employer names in session
  titles, a job-hunt repository — so wherever the index is written must not be
  somewhere it can be committed or published by accident.
- **No new runtime dependencies.** ai-mirror is stdlib Python by house style
  (`AGENTS.md`), and this should stay that way.

## Open questions

1. **Does reading require the control gate?** Control is currently a
   precondition for acting. An index is read-only, and there is a real argument
   for letting an agent orient itself before asking for control — and a real
   argument that the host's shape is itself private. This decides whether
   `desktop_index` sits inside or outside the ownership check.

2. **Where does the generated index live, if anywhere?** Returning it only
   through the MCP call means it never touches disk and cannot be committed. A
   file on disk is inspectable by the user and diffable over time, but given
   the personal-data constraint above it must not land anywhere a `git add -A`
   would catch it.

3. **Who writes the gotchas, and can an agent append to them?** They are the
   half of the value that cannot be generated. If only a human writes them they
   will lag; if an agent appends them, the file needs review before it is
   trusted, and an agent that records a wrong lesson has made things worse.

4. **Does this stay host-specific or become portable?** The parsing assumes
   this machine's nixarchy layout. Whether it should work on any nixarchy host,
   or is explicitly a p620 tool until someone needs otherwise, changes how much
   of the layout is allowed to be hard-coded.

5. **Is this the right lever to pull first?** Given the section above, an index
   addresses the guessing class but not the acting-blind class, and the second
   is what edited the user's configuration twice. If readable panel state is
   judged the more urgent of the two, this work should wait behind it rather
   than ship first and imply the problem is solved. My own reading is that the
   index goes first because it is cheap and informs what to verify — but that
   is a judgement about sequencing, not a fact, and it is the approver's to
   make.

6. **Is ai-mirror the right owner?** The data it describes belongs to nixarchy
   and omarchy; ai-mirror only consumes it. The counter-argument is delivery:
   ai-mirror is what agents already load, and its server instructions are the
   only channel that reaches every session regardless of project. If the answer
   is "nixarchy owns it", this intent moves repositories.
