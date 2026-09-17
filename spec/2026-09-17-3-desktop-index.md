---
status: approved
issue: 3
intent: intent/2026-09-17-3-desktop-index.md
---

# Spec: A desktop index, so an agent stops rediscovering this host

## Decisions carried from the intent's open questions

The intent left six. Answered here so the design has something to stand on;
each is a decision the approver can reverse.

1. **Reading does not require the control gate.** `status` already answers
   without it, and orienting before asking for control is the point. The gate
   exists to stop an agent *acting*, not to keep the host's shape secret from a
   server the user installed and launched themselves.
2. **The index never touches disk.** The CLI prints to stdout, the MCP tool
   returns a value. No cache file, no state file, nothing a `git add -A` can
   catch. This settles the personal-data constraint by construction rather than
   by `.gitignore`.
3. **The gotchas are hand-written and human-reviewed**, in `index/gotchas.md`
   in this repository. The generator only ever reads that file. An agent that
   learns something proposes a diff like anyone else; a wrong lesson recorded
   silently is worse than no lesson.
4. **Host-shaped, not host-hard-coded.** Nothing about p620 is special-cased.
   Every source is probed and absence shrinks the answer, so it works on any
   nixarchy host to the extent that host looks like this one, without claiming
   support for machines nobody has tested.
5. **The index goes first**, per the intent's reasoning: it is cheap, and it
   tells you which states are worth asserting later.
6. **ai-mirror owns it.** The data belongs to nixarchy, but delivery decides
   this: ai-mirror's MCP `instructions` are the only channel that reaches every
   agent session from every project directory.

## Design

One subcommand, `ai-mirror index`, and one MCP tool, `desktop_index`, sharing
an `index.py` module. Output is Markdown by default because the reader is
usually a language model; `--json` for programs.

### Sections, and why the default is small

459 `omarchy-*` commands and 4920 entries from `hyprctl binds` are both real
counts on this host. Returning either in full would produce something too
expensive to read at the start of every session, which is the one thing the
index cannot afford to be. So the payload is sectioned, and the default is the
small high-value set:

| Section | Default | Source | Size here |
| --- | --- | --- | --- |
| `state` | yes | `hyprctl version/monitors/workspaces -j` | ~10 lines |
| `keys` | yes | `~/.config/hypr/*.lua` | 36 rows |
| `plugins` | yes | `omarchy-plugin-list`, plugin manifests | 22 rows |
| `nav` | yes | `ai-mirror a11y-tree`, roles per application | ~8 lines |
| `gotchas` | yes | `index/gotchas.md` | hand-written |
| `apps` | no | `nixarchy-pkg state` | on request |
| `commands` | never in full | `# omarchy:summary=` headers | search only |

`--section <name>` adds one. `--find <query>` searches the 459 command
summaries and returns matches, which is how a caller actually uses that data —
"what changes the theme?" not "list everything".

### Keybindings: parse the Lua, not hyprctl

`hyprctl binds -j` returns 4920 entries, no labels, and opaque numeric
dispatcher arguments. The configuration is far better:

```lua
o.bind("SUPER + ALT + N", "nixarchy packages", "omarchy-shell shell toggle nixarchy.pkg '{}'")
```

Key, human label and command, already written down, 36 of them across six
`~/.config/hypr/*.lua` files. A regex over `o.bind(` yields the whole intent →
key → command map. `hyprctl binds` is still consulted for one thing: a count,
so the index can say when parsing found suspiciously few.

### The join that makes it worth building

A bind's command frequently names a plugin id:

```
SUPER + ALT + N  →  omarchy-shell shell toggle nixarchy.pkg '{}'
```

Matching that id against the plugin list gives each plugin its opening
keystroke without anyone maintaining a mapping. That single derived fact is
what the wallpaper incident cost: the binding existed, nothing connected it to
the plugin, and it was guessed instead.

### Navigation strategy, not coordinates

The intent forbids storing pixels. Instead each surface is classified live from
`a11y-tree`: an application whose node has children is `a11y` and should be
driven with `a11y_find`; one with none is `keyboard`. On this host QuickShell
reports `{"role":"application","name":"quickshell","states":[]}` with no
children, so the entire shell — bar and every panel — is `keyboard`, while
Electron and GTK applications expose full trees with bounds.

Reuse before reimplementation: `omarchy-plugin-list`, `omarchy-theme-list` and
`nixarchy-pkg state` already enumerate their own domains and are called rather
than reproduced. The index parses files only where no command exists.

### Degradation

Each section is independent and wrapped. A missing file or a renamed command
yields `_unavailable: <reason>` for that section and the rest still renders. A
half-index beats guessing, and ai-mirror must not break because nixarchy moved
a file.

### No cache

Every source is a small local file or a fast command. The whole thing is
regenerated per call. There is no invalidation logic because there is nothing
to invalidate.

## Alternatives rejected

- **`hyprctl binds` as the key source.** 4920 entries, no human labels, opaque
  arguments. Measured, not assumed.
- **Dumping all 459 command summaries.** Too large to read every session, which
  defeats the purpose. Replaced with `--find`.
- **Caching, or a daemon holding state in memory.** The intent forbids it: a
  stale index states a keybinding confidently and is worse than none. Nothing
  here is expensive enough to justify the invalidation problem.
- **A registry of pixel coordinates.** They drift silently — hovering the bar
  expands the tray and moves every widget. This was the largest single failure
  source in the session behind the intent.
- **Accessibility as the universal strategy.** QuickShell exposes no tree, so
  the shell can only be driven by keyboard. Verified above.
- **Reimplementing the enumerators.** `omarchy-plugin-list` and friends exist.
- **Owning this in nixarchy.** nixarchy owns the data, but ai-mirror is what
  agents load; server instructions are the delivery mechanism. Revisit if a
  second consumer appears.
- **Writing the index to a file for inspection.** Diffable and convenient, and
  it puts application lists and session titles somewhere a commit can catch
  them. Rejected on the personal-data constraint.

## Risks

- **Coupling to nixarchy's layout.** ai-mirror starts depending on paths it
  does not own; a rename upstream degrades sections silently. Mitigated by
  per-section availability reporting and a check that asserts non-empty
  sections on this host, so a break is visible rather than quiet.
- **Silent emptiness.** A parser that returns zero rows looks identical to a
  host with no keybindings. Every section reports its count, and the check
  asserts plausible minimums.
- **Context cost.** The default payload must stay small or callers will stop
  asking for it. Enforced by a test with a byte budget, not by intention.
- **The index describes, it cannot confirm.** It reports the keystroke that
  opens a panel; it cannot say the panel opened. That is the acting-blind gap
  the intent excludes, tracked as olafkfreund/nixarchy#749 — where honouring
  the existing `summon` payload now looks like the cheaper fix.
- **Personal data in transit.** Even without touching disk, the output names
  applications and workspaces. It goes only to the agent the user has already
  given a desktop-control server to, but it should not be pasted around.

## Verification

- **Unit tests**, stdlib `unittest`, per house style, over fixture files: a
  `bindings.lua` sample yields the expected key/label/command rows; a manifest
  directory yields the expected plugins; the key→plugin join resolves; a
  missing file degrades to `_unavailable` rather than raising.
- **Runtime check on this host**, asserting plausible minimums so a silently
  empty parser fails loudly: at least 30 keys, at least 20 plugins, `nav`
  classifying quickshell as `keyboard`, every default section present.
- **Budget test**: default Markdown output under an agreed byte ceiling.
- **`nix flake check`** and `python3 -m unittest discover -s tests` both green.
- **Acceptance, and the real proof**: an agent given only `desktop_index` —
  no screenshots, no grepping — opens the package panel and reaches the Options
  tab for PostgreSQL. That is precisely the sequence that failed in the session
  behind the intent.
