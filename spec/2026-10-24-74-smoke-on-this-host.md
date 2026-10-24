---
status: draft
issue: 74
intent: intent/2026-10-24-74-smoke-on-this-host.md
---

# Spec: the live smoke test passes on this host again

## Design

### 1. The measured table leaves the default index (intent decision 1b)

- **New file** `src/ai_mirror/measured.md`. It holds the "Measured
  examples, not a toolkit rule" paragraph, the per-app table and the
  Firefox hidden-workspace line, all moved verbatim from `gotchas.md`
  ("Accessibility trees are per-application", lines ~146-171). It gets a
  one-line `# Measured: what a11y_act does, per app` heading.
- **`index.py`:**
  - Add `def measured()`, which reads that file the way `gotchas()` does.
  - Add `'measured'` to `ALL_SECTIONS`, but not to `DEFAULT_SECTIONS`.
  - Register it in `build()`'s builders.
  - Make `_render_section` treat `measured` like `gotchas` (the text is
    already markdown).
- **In `gotchas.md`,** the removed block becomes one line: "Per-app results
  (what each action did in GTK4, Chrome, Firefox): `index --section
  measured`."
- **Trims,** with the same advice in fewer words and no fact dropped:
  - "Typing into a menu, panel or launcher" (~2.7 KB) to at most 1.4 KB.
  - "Chrome ignores the middle mouse button" (~1 KB) to at most 0.5 KB.
- **Target:** this host's default payload ≤ 20,500 bytes, leaving about
  1.5 KB of headroom under 22,000.
- **Other wiring:**
  - The MCP `index` description names `section=measured`.
  - The CLI `--section` help lists it.
  - `docs/usage.md:133` and `README.md:97` link `src/ai_mirror/measured.md`.
  - `AGENTS.md`'s code map gets a row for it.

### 2. `check_wait` uses a panel this host has (intent decision 2b)

In `tests/smoke.py` `check_wait`:

1. **Pick a candidate** from `index.plugins()`: rows that have
   `enabled is True` and an `opens_with` key, where `kinds` includes `menu`
   or `panel`, and the id is not `olafkfreund.ai-mirror`. Sort them by id
   for repeatability. If there are none, print `SKIP: check_wait -- no
   enabled plugin opens a panel from a key on this host` and return.
2. **Discover the layer.**
   1. Snapshot the `host.layers()` namespaces.
   2. Press the plugin's `opens_with` key through `api.run('input', ...)`
      with the focused window's address. That's the same call it makes
      today; the key string is split on ` + ` into modifiers and a key.
   3. Poll `host.layers()` for up to 5 s for a namespace that wasn't there
      before.
   4. Close it with `omarchy-shell -q shell hide <id>`.
   5. If nothing appeared, try the next candidate. If none work, the check
      **fails**, naming every id tried, because a key that opens nothing is
      a real finding.
3. **The existing checks, unchanged in kind,** against that namespace:
   1. absent confirms at once
   2. press, then the layer confirms (`opened_ms`)
   3. hide, then absent confirms
   4. a missing layer gives `not_confirmed` in about 1 s
4. **`finally`** hides the chosen id (no longer the hard-coded
   `nixarchy.pkg`), then `control.set_owner('off', 'human')` and
   `HELPER.stop()`, as today.

The PASS line names the plugin and the namespace.

### 3. The unit test

`test_the_default_payload_stays_small_enough_to_read` keeps 22,000. A new
test asserts that the default `build()` has no `measured` section, that
`build({'section': 'measured'})` returns the table (it contains "set_value"),
and that `gotchas.md` no longer contains a table row starting `| Chrome`.

## Alternatives rejected

- **Raise the budget** (decision 1a): it grows again with every measurement.
- **Hard-code another panel** (decision 2a): it breaks on the next host
  that turns that plugin off.
- **Make `check_wait` press the key once:** the discovery press is what
  learns the layer name, since manifests don't declare it. Pressing twice
  costs about 1 s.

## Risks

- **An agent misses the table:** an agent that relied on the default index
  for per-app facts must now ask for `measured`. The one-line pointer and
  the MCP description name it.
- **A panel with side effects:** a discovered panel could do something on
  open. Only `menu`/`panel` kinds are chosen, and they are opened and
  closed without input in between. `nixarchy.pkg`'s Return trap only
  matters with typing, which this check never does.
- **Rendering per monitor:** layers render on the focused monitor. The
  check keeps its focus on `DP-1`, as today.

## Verification

- `python3 -m unittest discover -s tests` passes, and `nix flake check`
  passes.
- `ai-mirror index | wc -c` on this host is ≤ 20,500.
- `ai-mirror index --section measured` shows the table.
- Live: `tests/smoke.py` passes end to end on this host, printing PASS for
  index, wait (naming the plugin) and main. Afterwards control is off and
  no panel or test window is left open.
