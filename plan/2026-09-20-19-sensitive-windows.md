---
status: approved
issue: 19
spec: spec/2026-09-20-19-sensitive-windows.md
---

# Plan: refuse the frame, name the kind, and say plainly it is a heuristic

## The approved decisions, in full

Implementable without opening the intent or the spec.

**The problem.** Nothing here declines to capture based on what is in a window,
so `screenshot` will photograph a 1Password vault, a `pinentry` prompt
mid-passphrase or a bank dashboard, base64 it (`mcp.py:106`) and hand it to a
model. 1Password is installed on this machine and `gcr-prompter` is in the
store. It sits badly beside #11, which made taking control a request a human
answers, and #15, which made the test suite unable to reach the desktop at all.

Decisions carried over:

1. **Refuse, do not redact.** A redaction off by a few pixels is a leak that
   looks like it worked. Refusing matches what this repository chose in #15 and
   #18: say so rather than hand back something.
2. **The unit is the captured rectangle, not the focused window.**
   `control.screenshot()` (`control.py:405`) already resolves a rectangle from
   `region`, a named output, or the whole layout, and `host.windows()`
   (`host.py:55`) already returns `at`, `size` and `workspace` for every mapped
   client. Every visible window intersecting it is checked.
3. **Class AND title.** Measured here, a Gmail window reports
   `class='chrome-fmgjjmmmlfnkbppncabfkddbjimcfncm-Profile_4'`, an opaque
   extension id identifying nothing. Only the title says what it is, and a bank
   as a web app would look identical to a class-only guard.
4. **A `MirrorError` with its own code.** The repository answers refusals with a
   structured code — `bad_request`, `not_owner`, `stale_generation`,
   `stale_node`, `unavailable`, `unsupported` — and an agent reads the code. A
   new one distinguishes "never" from "failed, try again".
5. **The detail names a category, never the title**, and names the way forward.
   Titles here carry an inbox count, an email address and what is being watched.
6. **`a11y_tree` and `a11y_find` are excluded**, deliberately. They deserve the
   same protection — a tree of a credential prompt is machine-readable text,
   worse than a picture — but it is a tree walk with no rectangle needing a
   per-node decision. Bundling would turn a small clearly-right change into a
   large arguable one. Filed separately in step 6.
7. **A hard-coded floor plus additions.** Removing the floor by configuration is
   not offered: a misconfiguration would silently reinstate the exposure.
8. **`gotchas.md` says it is a heuristic**, because `index` serves that file to
   every agent and an agent that thinks the screen is safe behaves differently.

## Steps

**1. New `src/ai_mirror/privacy.py`.**
Two regular expressions seeded from omarchy-hermes-companion
`daemon/perception.py:20-33` (MIT, attributed in the module docstring), and
`kind(cls, title) -> str | None` returning a short category or None. It must not
return, log or embed the matched text. Its own module because it is one concern
and because a seam nobody can find is a seam somebody bypasses.
→ verify by a unit test per seeded pattern, plus one asserting the returned
string contains neither class nor title.

**2. `privacy.py` — which windows a rectangle contains.**
`covering(rect) -> list[dict]` over `host.windows()`: keep mapped windows on a
visible workspace whose `at`/`size` intersects. `host.windows()` already drops
unmapped clients.
→ verify by unit tests over fabricated window lists: intersecting, adjacent,
non-visible workspace, other output.

**3. `control.py:405` — the guard in `screenshot()`.**
After the rectangle is resolved and before `grim` runs, raise
`MirrorError('sensitive', …)` if anything covering it matches. One place: every
agent-visible frame comes through here, including the one `mcp.py:106` base64s.
→ verify by a test that a fabricated sensitive window refuses with that code,
and that an ordinary desktop still captures.

**4. The refusal detail.**
`"<kind> is visible in that area, so nothing was captured. Capture a specific
region that excludes it, or ask the user to close it."`
→ verify by reading it, and a test asserting no title substring appears.

**5. `gotchas.md` — one entry.**
That captures are refused over credential prompts and password managers, that it
is matched on window class and title, and **that it is best-effort**: it misses
things and it misfires. `index` reads this on every orientation, so it earns its
length by being the thing that stops an agent trusting the screen is safe.
→ verify by `ai-mirror index` containing it.

**6. File the `a11y_tree` follow-up**, referencing this issue and decision 6, so
the exclusion is tracked rather than forgotten.
→ verify by the issue URL, linked from the PR.

## Tests

```
nix develop -c python3 -m unittest discover -s tests -v
nix flake check
```

Expected green. No test reaches the real desktop (#15's invariant): window lists
are fabricated, and `guard.arm()` in `Base.setUp` already makes a slip loud.

## Rollback

`git revert` the implementation commits. `privacy.py` is new and additive;
`screenshot()` gains one check. Nothing outside the repository changes, and no
capture that succeeds today changes its output.
