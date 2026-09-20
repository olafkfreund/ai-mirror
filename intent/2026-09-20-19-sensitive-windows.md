---
status: draft
issue: 19
author: olafkfreund
---

# Intent: a screenshot will photograph a password manager, and nothing stops it

## Problem

Nothing in this repository declines to capture a window because of what is in
it. `grep -riE "1password|keepass|pinentry|sensitive|incognito"` over `src/`
returns only the AT-SPI state name `sensitive`, which is unrelated.

So `screenshot` will photograph a 1Password vault, a `pinentry` prompt
mid-passphrase, a `gcr-prompter` dialog or a bank's dashboard, base64 it
(`mcp.py:106`) and hand it to a model. `control.screenshot()` (`control.py:253`)
resolves a rectangle from `region` or `output` and shoots it; nothing looks at
what is underneath.

Both are installed here. 1Password is on this machine and `gcr-prompter` is in
the store, so this is a live exposure rather than a hypothetical one.

It sits badly beside what this repository already does. #11 made taking control
a request a human answers. #15 made the test suite structurally unable to reach
the desktop. Photographing a passphrase prompt is the gap between those two.

**Two things found while scoping, and both change the shape of any answer:**

1. **A class blocklist cannot see a Chrome web app.** Measured on this desktop,
   a Gmail window reports
   `class='chrome-fmgjjmmmlfnkbppncabfkddbjimcfncm-Profile_4'` — an opaque
   extension id. Only its title, `Gmail - Freundcloud - Inbox (7) - <address>`,
   says what it is. A bank opened as a web app would be invisible to a
   class-based guard, and web apps are how this desktop runs most things.
2. **The title is itself the sensitive material.** The same window's title
   carries an inbox count and an email address; others on screen right now carry
   what is being watched and which media are missing. So the title is the only
   usable signal *and* a thing that must not be echoed back in a refusal.

## Proposed outcome

- A capture that would include a credential prompt, a password manager or a
  private browsing window does not happen, and the caller is told why.
- The reason given is useful without being a leak: it names the kind of thing
  refused, never the window's title.
- The guard is visible enough that somebody adding a capture path later trips
  over it rather than bypassing it by not knowing.
- What is refused is discoverable and adjustable, because any list of this sort
  is wrong for somebody.

## Affected users and systems

- Every agent calling `screenshot`, and anything built on the frames it returns.
- `src/ai_mirror/control.py` (`screenshot`), `src/ai_mirror/api.py` (the
  `screenshot` branch), `src/ai_mirror/mcp.py` (the frame it base64s), and
  `gotchas.md` if the refusal needs explaining to agents.
- Possibly `a11y_tree` and `a11y_find`, which are arguably worse: an
  accessibility tree of a password manager is machine-readable text, not a
  picture. Today neither is guarded either.
- The human, who is the person this is for.

## Constraints

- **A refusal must not leak what it refused.** "the focused window is a password
  manager" is defensible; the title is not. This is the constraint most easily
  got wrong while trying to be helpful.
- **Must not depend on a class alone.** See the Gmail finding above.
- **Must not quietly return a blank or partial frame.** A capture that silently
  omits something is worse than one that refuses: the agent believes it saw the
  screen. #15's guard and #18's empty-find note both chose "say so" over "return
  something", and this should match.
- **Must not become a security claim it cannot keep.** A blocklist is a
  heuristic. It will miss things and it will misfire, and the documentation has
  to say so rather than imply the screen is now safe.
- Must not require a new dependency. `hyprctl clients` already gives class and
  title.
- Tests must not reach the real desktop (#15's invariant).

## Open questions

1. **Refuse, or redact?** Refusing is honest and simple. Blacking out the
   offending window keeps the rest of the screen usable, needs compositing, and
   has more ways to be subtly wrong.
2. **What is the unit — the focused window, or anything visible?** `screenshot`
   takes a region or a whole output. A guard keyed on the focused window does
   not cover a password manager sitting beside the thing being captured, and
   that is the harder and more honest half.
3. **Does this cover the accessibility tools too?** An a11y tree of a credential
   prompt is more directly exploitable than a picture of one.
4. **Whose list, and can the human change it?** A hard-coded floor plus
   additions is what I would expect, but a floor nobody can lower is also a
   defensible choice for this particular subject.
5. **How is it tested?** The desktop states that matter — a pinentry on screen —
   are the ones a test may not create. Probably the matcher is tested directly
   and the wiring separately.

## Prior art

[PSthelyBlog/omarchy-hermes-companion](https://github.com/PSthelyBlog/omarchy-hermes-companion),
MIT, solves the same problem for an always-on screen-watcher at
`daemon/perception.py:20-33`: two regular expressions, one over the window class
and one over the title, and no frame is produced when either matches. The lists
are reusable with attribution and are a reasonable floor. Its title list already
includes banking and private-browsing terms, which is the half that matters most
here given the Chrome web app finding.
