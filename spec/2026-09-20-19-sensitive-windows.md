---
status: approved
issue: 19
intent: intent/2026-09-20-19-sensitive-windows.md
---

# Spec: refuse the frame, name the kind, and say plainly it is a heuristic

## The intent's open questions, answered

1. **Refuse, do not redact.** A redaction that is off by a few pixels is a leak
   that looks like it worked. A refusal is one branch, and it matches what this
   repository already chose twice: #15's guard and #18's empty-find note both
   say so rather than hand back something.
2. **The unit is the captured rectangle, not the focused window.**
   `control.screenshot()` (`control.py:253`) already resolves a rectangle from
   `region`, a named `output`, or the whole layout, and `host.windows()` already
   returns `at`, `size` and `workspace` for every mapped client. Every visible
   window intersecting the rectangle is checked. A password manager beside the
   thing being captured is caught.
3. **`a11y_tree` and `a11y_find` are NOT in this spec.** They deserve the same
   protection — an accessibility tree of a credential prompt is machine-readable
   text, worse than a picture of one — but it is a different mechanism: a tree
   walk with no rectangle, needing a per-node decision rather than one check
   before a capture. Folding it in would make a small, clearly-right change into
   a large, arguable one. Filed separately, and the intent's concern is recorded
   rather than dropped.
4. **A hard-coded floor plus additions**, read from the same state directory the
   control file lives in. A floor nobody can lower is defensible for this
   subject; the additions exist because any such list is wrong for somebody.
5. **The matcher is tested directly; the seam is tested with fabricated window
   lists.** The desktop states that matter are ones a test must not create —
   #15's invariant already forbids tests reaching the desktop at all.

## Design

### 1. One matcher, two regular expressions

A class pattern and a title pattern, seeded from
[omarchy-hermes-companion](https://github.com/PSthelyBlog/omarchy-hermes-companion)
`daemon/perception.py:20-33` (MIT, attributed in the source). Both are needed:
measured on this desktop a Gmail window reports
`class='chrome-fmgjjmmmlfnkbppncabfkddbjimcfncm-Profile_4'`, an opaque extension
id that identifies nothing. Only its title says what it is, and a bank opened as
a web app would look identical to a class-only guard.

The matcher returns **a category**, never the text it matched on.

### 2. The guard sits in `control.screenshot()`

It is the single place a rectangle becomes pixels. Everything agent-visible
comes through it, including the frame `mcp.py:106` base64s, so one check covers
the surface rather than each caller remembering.

It asks `host.windows()` for mapped windows on a visible workspace and refuses
if any intersecting one matches — the same query the screenshot path already
makes to resolve its geometry.

### 3. The refusal is a `MirrorError` with its own code

The repository already answers refusals with a structured code — `not_owner`,
`stale_generation`, `unavailable` — and an agent is expected to read the code
rather than the prose. A new code makes this distinguishable from a capture that
merely failed, which matters: one means try again, the other means never.

The detail names a category and nothing else:

> a password manager is visible in that area, so nothing was captured. Capture a
> specific region that excludes it, or ask the user to close it.

The title never appears. On this desktop right now the titles carry an inbox
count, an email address, and what is being watched.

### 4. `gotchas.md` says it is a heuristic

One entry, in the file `index` already serves to every agent. It states that a
blocklist misses things and misfires, because an agent that believes the screen
is now safe behaves differently from one that knows it is best-effort — and the
whole value of `gotchas` is telling an agent what is actually true here.

## Alternatives rejected

- **Guard the focused window only.** What the prior art does, and it has an
  easier problem: it only ever captures the focused window. `screenshot` takes a
  region or a whole output, so this would pass the case worth catching.
- **Redact the region.** Keeps the rest of the frame usable, needs image
  manipulation, and fails silently when it is slightly wrong.
- **Return a blank frame.** Worse than refusing: the agent believes it saw the
  screen.
- **Include `a11y_tree` here.** See answer 3. Right to do, wrong to bundle.
- **Match by pid against a process list.** More precise, and a `/proc` walk costs
  323 ms on this host's 21,731 processes (measured for nixarchy-voice#47) where
  a window query costs a fraction of that.
- **Make the floor configurable away.** Additions yes; removing the built-in
  floor would let a misconfiguration silently reinstate the exposure.

## Risks

- **Over-refusal.** A password manager anywhere on the captured output blocks the
  capture. Mitigated by the refusal naming the narrower-region route, and it is
  the cost of the safe default.
- **Title false positives.** A page about passwords is refused. The right side to
  err on.
- **A heuristic mistaken for a guarantee.** The reason design 4 exists.
- **`pinentry` and `gcr-prompter` may not appear as mapped clients.** Layer
  surfaces on this desktop are only `omarchy-background` and `omarchy-bar`, so
  they should be ordinary windows — but neither was running to confirm, and they
  are the case this most wants to catch.
- **A window can appear between the check and `grim`.** Milliseconds, and not
  closable without compositor support. Stated rather than engineered around.

## Verification

**The matcher, directly.** Each seeded pattern matches what it should, and the
category never contains the matched text. A Gmail-titled window with an opaque
`chrome-*` class is caught by title — the case a class-only guard misses.

**The seam, with fabricated window lists.** No real desktop, per #15. A sensitive
window intersecting the rectangle refuses with the new code; the same window on
a non-visible workspace does not; on another output does not; an ordinary window
never refuses.

**The refusal, by reading it.** It must carry the new code, name a category,
contain no title, and name the way forward.

**Nothing regressed.** `nix flake check` green, and an ordinary `screenshot`
behaves exactly as before.

**Not verified here.** Whether a live `pinentry` or `gcr-prompter` is a mapped
client with a usable class. That needs one on screen and is the first thing to
check by hand when this lands.
