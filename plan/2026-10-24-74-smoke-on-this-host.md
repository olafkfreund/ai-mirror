---
status: approved
issue: 74
spec: spec/2026-10-24-74-smoke-on-this-host.md
---

# Plan: the live smoke test passes on this host again

Self-contained. Branch `fix/74-smoke-on-this-host` from master `77df700`.

## Approved decisions (from the spec)

1. **The measured table leaves the default index.**
   - The "Measured examples, not a toolkit rule" paragraph, the per-app
     table and the Firefox hidden-workspace line move word for word into a
     new `src/ai_mirror/measured.md`, under `# Measured: what a11y_act
     does, per app`.
   - That file is served as the opt-in index section `measured`; it is in
     `ALL_SECTIONS` and not in `DEFAULT_SECTIONS`.
   - `gotchas.md` keeps one pointer line in its place.
   - "Typing into a menu, panel or launcher" is trimmed to ≤ 1.4 KB and
     "Chrome ignores the middle mouse button" to ≤ 0.5 KB, dropping no fact.
   - Target: this host's default `ai-mirror index` ≤ 20,500 bytes. The
     22,000 cap in `tests/smoke.py` and the unit test stays.
   - The MCP description, CLI help, `docs/usage.md`, `README.md` and the
     `AGENTS.md` code map name the new section or file.
2. **`check_wait` uses a panel this host has.**
   - It picks enabled plugins with an `opens_with` key and a `menu` or
     `panel` kind, excluding `olafkfreund.ai-mirror`, sorted by id. With
     none, it prints a SKIP line and returns.
   - It discovers the layer namespace by pressing the key once and diffing
     `host.layers()`. A key that opens nothing moves on to the next
     candidate. If no candidate opens anything, the check fails and names
     every id it tried.
   - Then it runs the four existing checks against that namespace.
3. **A new unit test** proves the table is out of the default build and
   served by `measured`.

## Steps

1. **`src/ai_mirror/measured.md` (new) and `src/ai_mirror/gotchas.md`.**
   - Move `gotchas.md:146-172` (from `**Measured examples, not a toolkit
     rule**` through `and GTK4 do.`) verbatim into `measured.md`, after the
     line `# Measured: what a11y_act does, per app` and a blank line.
   - In `gotchas.md`, put this one line in its place: `Per-app results
     (what each action did in GTK4, Chrome, Firefox): \`index --section
     measured\`.`
   - Trim `## Typing into a menu, panel or launcher` (`gotchas.md:220`,
     2,746 bytes to the next heading) to ≤ 1,400 bytes. Trim `## Chrome
     ignores the middle mouse button` (`gotchas.md:289`, 1,075 bytes) to
     ≤ 500 bytes. Keep every measured number, command and named key; cut
     the narration.
   → verify by:
   - `grep -c '^| Chrome' src/ai_mirror/gotchas.md` printing 0
   - the two `awk '/^## Typing into a menu/,/^## A refusal/'` and
     `awk '/^## Chrome ignores/,/^## What you launch/'` byte counts
     (`| wc -c`) within the limits, measured including the next heading line
   - `git diff --stat` showing the table lines removed in one file and added
     in the other
   Traps:
   - `gotchas.md` is read only by `index.gotchas()`; there is no generator.
   - `flake.nix` installs the package directory wholesale, so a new `.md`
     next to `gotchas.md` needs no packaging change.

2. **`src/ai_mirror/index.py`.**
   - `:48`: `ALL_SECTIONS = DEFAULT_SECTIONS + ('apps', 'measured')`.
   - After `gotchas()` (`:347-350`), add `measured()`, reading
     `measured.md` the same way, with the docstring "Per-app a11y results.
     Opt-in: too long for every session's first read."
   - `:406-407`: add `'measured': measured` to `builders`.
   - `:433`: `if name in ('gotchas', 'measured'):`.
   → verify by:
   - `python3 -m ai_mirror index --section measured` (from `src/`)
     printing the table
   - `python3 -m ai_mirror index | wc -c` ≤ 20,500 on this host, run with
     the live `HYPRLAND_INSTANCE_SIGNATURE` exported (the session model
     runs this if the coder's shell cannot reach Hyprland)
   Traps: `index` is derived per call, never cached or written to disk.
   Keep it so.

3. **Wiring:**
   - `src/ai_mirror/mcp.py:50`: change the description's "section=apps
     adds declared apps/services;" to "section=apps adds declared
     apps/services, section=measured what each a11y_act did per app;".
   - `src/ai_mirror/cli.py:133`: the help becomes "add a section
     (repeatable: apps, measured); default is state, keys, plugins, nav,
     gotchas".
   - `docs/usage.md:133`: replace "Measured cases: `src/ai_mirror/gotchas.md`."
     with "Measured cases: `src/ai_mirror/measured.md` (`index --section
     measured`)."
   - `README.md:97`: the link target and text become
     `src/ai_mirror/measured.md`.
   - `AGENTS.md:33`: after the `gotchas.md` row, add the row
     ``| `src/ai_mirror/measured.md` | Per-app a11y_act results; served only by `index --section measured` |``.
   → verify by `grep -n measured src/ai_mirror/mcp.py src/ai_mirror/cli.py
   docs/usage.md README.md AGENTS.md` showing one hit per file, and every
   linked path existing.
   Traps:
   - No new MCP tool. The `section` schema (`array of STR`) already
     accepts the name, and `build()` validates it against `ALL_SECTIONS`.
   - `CLAUDE.md` is a symlink to `AGENTS.md`; edit `AGENTS.md` only.

4. **`tests/test_invariants.py`.** After
   `test_the_default_payload_stays_small_enough_to_read` (`:499-520`), add
   `test_the_measured_table_is_opt_in`, with the same fakes (`state` and
   `nav` patched to raise) so it never reaches the desktop. It asserts:
   - `'measured' not in index.build({})`
   - `'set_value' in index.render(index.build({'section': ['measured']}))`
   - no line of `index.gotchas()['text']` starts with `| Chrome`
   → verify by `python3 -m unittest discover -s tests -v` passing, with the
   22,000 test unchanged.
   Traps: `Base.setUp` arms the guard. Patch `state` and `nav` as the
   neighbouring test does, rather than disarming.

5. **`tests/smoke.py` `check_wait` (`:115-161`).**
   - Before `take_control()`, compute the candidates:
     `[p for p in index.plugins()['items'] if p.get('enabled') is True and
     p.get('opens_with') and {'menu', 'panel'} & set(p.get('kinds') or [])
     and p['id'] != 'olafkfreund.ai-mirror']`, sorted by `id`. If there are
     none, print `SKIP: check_wait -- no enabled plugin opens a panel from a
     key on this host` and return.
   - A local `press(keys)` does what the current inline call does:
     `api.run('input', {'generation': gen, 'window': host.focused_address(),
     'actions': [{'type': 'key', 'keys': [last], 'modifiers': rest}]})`,
     where `*rest, last = keys.split(' + ')`.
   - Discovery loop over the candidates:
     1. `before = {l['namespace'] for l in host.layers()}`
     2. `press(p['opens_with'])`
     3. poll `host.layers()` every 0.1 s for up to 5 s for a namespace not
        in `before`
     4. `omarchy-shell -q shell hide <id>`
     5. take the first that produced one, set `chosen` and `ns`, and break
   - No candidate produced a layer: `raise AssertionError(f'no panel
     appeared for {ids}')`.
   - Then the existing four checks, with `'nixarchy-pkg-menu'` replaced by
     `ns`, `['N']`/`['SUPER','ALT']` by `press(chosen['opens_with'])`, and
     the hide by `chosen['id']`. Before the first check, wait for `ns`
     absent (it is already closing from discovery).
   - `finally`: hide `chosen['id']` if one was chosen; `set_owner('off',
     'human')` and `HELPER.stop()` as today.
   - The PASS line names the plugin id and `ns`.
   → verify by `python3 -c "import ast;ast.parse(open('tests/smoke.py').read())"`
   and the unit tests (smoke is not part of them). The live run is step 6.
   Traps:
   - Re-read the generation after `take_control()`, as today.
   - Keep focus on `DP-1`: panels render on the focused monitor.
   - Never type into a discovered panel. `nixarchy.pkg`'s Return writes
     configuration.

6. **Live verification (session model, under the human's grant).** Run
   `AI_MIRROR_HELPER=$(nix build .#ai-mirror-input --print-out-paths)/bin/ai-mirror-input
   python3 tests/smoke.py` from `nix develop`, with the live
   `HYPRLAND_INSTANCE_SIGNATURE`. The human presses A for each
   `take_control()`.
   → verify by:
   - PASS lines for index (≤ 20,500 bytes), wait (naming the plugin and
     namespace) and main
   - `ai-mirror status` showing `owner: off`
   - `hyprctl layers` showing no plugin panel left open
   Record the measured bytes, the plugin and the namespace here.

7. **PR (session model).** Run the fresh Opus review against this plan and
   `git diff master...HEAD`. Then open a PR linking intent, spec and plan
   and saying which steps the coder did. Merge when CI is green, and close
   #74.

## Execution

Steps 1-5 edit eight files, so one `coder` does them in order. It cannot
commit; the session model commits each step and names it. Steps 6-7 are the
session model's.

## Tests

```sh
python3 -m unittest discover -s tests -v
nix flake check
python3 -m ai_mirror index | wc -c        # ≤ 20500
python3 -m ai_mirror index --section measured | grep -c set_value   # ≥ 1
```

## Rollback

Revert the PR. Nothing outside the repo changes: no config, no state file.
