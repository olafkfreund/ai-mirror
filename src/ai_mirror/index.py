"""What this host looks like, so an agent stops rediscovering it.

Everything here is derived from local files and fast commands on every call.
Nothing is cached: a stale index that states a keybinding with confidence is
worse than no index, and none of these sources is expensive enough to justify
an invalidation problem.

Nothing is written to disk either. The output names applications, workspaces
and sessions, which describe the person using the machine; keeping it to a
return value is what stops it landing in a commit.

Sections are independent. A missing file or a renamed command yields
`_unavailable` for that section and the rest still renders -- a half index
beats guessing, and this must not break because nixarchy moved a file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

# `o.bind("SUPER + ALT + N", "nixarchy packages", "omarchy-shell ...")`. The
# config already pairs a key with a human label and a command, which is why it
# beats `hyprctl binds`: that returns thousands of rows with neither.
#
# A regex over the whole call is not enough. Real binds also take a Lua
# function where the command goes, and build their key by concatenation:
#
#   o.bind("SUPER + " .. key, "Workspace " .. group, function() ... end)
#   o.bind("SUPER + CTRL + G", "Reclaim windows", grab_rogue_windows)
#
# Matching only the quoted form silently dropped 14 of 36 on this host,
# including every workspace movement key. So the call site is found by regex
# and its arguments are split properly.
BIND_CALL_RE = re.compile(r'\bo\.bind\(')

# A plugin id inside a bind's command, e.g. `shell toggle nixarchy.pkg '{}'`.
PLUGIN_ID_RE = re.compile(r'\b([a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+)\b')

SUMMARY_RE = re.compile(r'^#\s*omarchy:summary=(.+)$', re.MULTILINE)

HYPR_DIR = Path.home() / '.config/hypr'
PLUGIN_DIR = Path.home() / '.config/omarchy/plugins'

DEFAULT_SECTIONS = ('state', 'keys', 'plugins', 'nav', 'gotchas')
ALL_SECTIONS = DEFAULT_SECTIONS + ('apps',)


def sh(*argv, timeout: float = 10.0) -> str:
    """Run a command and return stdout, or raise with something readable."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[:200]
                           or f'{argv[0]} exited {done.returncode}')
    return done.stdout


def _section(fn, *args) -> dict:
    """Never let one broken source take the whole index down with it."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - a section failing is not fatal
        return {'_unavailable': f'{type(exc).__name__}: {exc}'.strip()[:200]}


# ------------------------------------------------------------------ sections

def state() -> dict:
    """Compositor version, dispatch form, and where the screens are."""
    from . import host

    version = sh('hyprctl', 'version').splitlines()[0].strip()
    workspaces = json.loads(sh('hyprctl', 'workspaces', '-j'))
    return {
        'hyprland': version,
        # The old `hyprctl dispatch workspace 8` form is a syntax error on
        # 0.4x+, and a dispatch that matches nothing still reports ok.
        'dispatch': 'hyprctl dispatch \'hl.dsp.focus({ workspace = "8" })\'',
        'monitors': host.monitors(),
        'workspaces': sorted(w['id'] for w in workspaces),
        'occupied': sorted(w['id'] for w in workspaces if w.get('windows')),
    }


def _strip_lua(text: str) -> str:
    """Blank out comments and long strings, keeping every byte offset.

    Without this a commented-out line is read as a live binding -- which is
    precisely the "agent confidently presses the wrong key" failure this whole
    module exists to prevent. Replacing rather than deleting keeps offsets
    aligned so the remaining code can still be scanned in place.
    """
    out, i, n = list(text), 0, len(text)
    while i < n:
        ch = text[i]
        if ch in '"\'':                                   # short string
            quote, i = ch, i + 1
            while i < n and text[i] != quote:
                i += 2 if text[i] == '\\' else 1
            i += 1
        elif text.startswith('--', i):
            long_open = re.compile(r'--\[(=*)\[').match(text, i)
            if long_open:                                 # --[[ block comment ]]
                close = text.find(f']{long_open.group(1)}]', long_open.end())
                stop = n if close < 0 else close + long_open.end() - long_open.start() - 2
            else:                                         # -- line comment
                stop = text.find('\n', i)
                stop = n if stop < 0 else stop
            for j in range(i, stop):
                if out[j] != '\n':
                    out[j] = ' '
            i = stop
        else:
            long_open = re.compile(r'\[(=*)\[').match(text, i)
            if long_open:                                 # [[ long string ]]
                mark = len(long_open.group(1)) + 2        # [[ or [=[ etc.
                close = text.find(f']{long_open.group(1)}]', long_open.end())
                stop = n if close < 0 else close + mark
                # Rewrite the delimiters as plain quotes so the argument
                # splitter still sees one argument, and blank anything inside
                # that would otherwise end it early.
                for j in range(i, min(i + mark, n)):
                    out[j] = ' '
                for j in range(max(stop - mark, 0), stop):
                    out[j] = ' '
                out[min(i + mark, n) - 1] = '"'
                out[stop - 1] = '"'
                for j in range(i + mark, max(stop - mark, i + mark)):
                    if out[j] in '"\'':
                        out[j] = ' '
                i = stop
            else:
                i += 1
    return ''.join(out)


def _split_args(text: str, start: int) -> list[str]:
    """The argument list of a call, split on top-level commas.

    Quotes and nesting are respected so a comma inside a string or an inline
    `function() ... end` does not end an argument.
    """
    args, buf, depth, quote, i = [], [], 0, None, start
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == '\\' and i + 1 < len(text):
                i += 1
                buf.append(text[i])
            elif ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
            buf.append(ch)
        elif ch in '([{':
            depth += 1
            buf.append(ch)
        elif ch in ')]}':
            if ch == ')' and depth == 0:
                args.append(''.join(buf).strip())
                return args
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    return args


def _literal(arg: str) -> tuple[str, bool]:
    """A Lua expression as text, plus whether it was a plain string.

    `"SUPER + " .. key` cannot be resolved without running the config, so the
    literal part is kept and the rest marked. Saying "SUPER + <computed>" is
    more use to a reader than dropping the binding entirely.
    """
    arg = ' '.join(arg.split())
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in '"\'':
        inner = arg[1:-1]
        if arg[0] not in re.sub(r'\\.', '', inner):
            return re.sub(r'\\(.)', r'\1', inner), True
    parts = []
    for piece in arg.split('..'):
        piece = piece.strip()
        if len(piece) >= 2 and piece[0] == piece[-1] and piece[0] in '"\'':
            parts.append(piece[1:-1])
        elif piece.startswith('function'):
            parts.append('<lua function>')
        elif piece == 'nil':
            parts.append('')
        else:
            parts.append(f'<{piece}>')
    return ''.join(parts).strip(), False


def keys() -> dict:
    """Every labelled keybinding, from the Lua that already describes them."""
    # An empty glob over a directory that does not exist is indistinguishable
    # from a host with no keybindings, so say which it is.
    if not HYPR_DIR.is_dir():
        raise FileNotFoundError(f'{HYPR_DIR} does not exist')
    binds, files = [], sorted(HYPR_DIR.glob('*.lua'))
    for path in files:
        if '.bak' in path.name or '.decoy' in path.name:
            continue
        text = _strip_lua(path.read_text(errors='replace'))
        for call in BIND_CALL_RE.finditer(text):
            args = _split_args(text, call.end())
            if len(args) < 2:
                continue
            combo, exact = _literal(args[0])
            label, _ = _literal(args[1])
            command, _ = _literal(args[2]) if len(args) > 2 else ('', True)
            binds.append({'keys': ' '.join(combo.split()),
                          'label': label,
                          'command': command,
                          'computed': not exact,
                          'source': path.name})
    # Two binds on one combo is not an error, it is a race the reader needs to
    # know about: whichever file loads last wins, and pressing the key does
    # something other than what the first row promises. SUPER + H is both nixi
    # and voxtype on this host.
    seen: dict[str, int] = {}
    for bind in binds:
        seen[bind['keys']] = seen.get(bind['keys'], 0) + 1
    for bind in binds:
        if seen[bind['keys']] > 1 and bind['keys']:
            bind['duplicate'] = True

    out = {'binds': binds, 'files': [p.name for p in files],
           'duplicates': sorted(k for k, n in seen.items() if n > 1 and k)}
    try:
        # Not a source, a sanity check: thousands of raw binds against a
        # handful of parsed ones means the regex stopped matching.
        out['hyprctl_bind_count'] = len(json.loads(sh('hyprctl', 'binds', '-j')))
    except Exception:  # noqa: BLE001 - advisory only
        pass
    return out


#   omarchy-shell shell toggle nixarchy.pkg '{}'   opens it
#   omarchy-shell shell hide   nixarchy.pkg        closes it
# Both name the plugin, so matching the id alone once labelled `hide` as the
# key that opens the panel. Only an opening verb counts.
OPENS_RE = re.compile(r'\b(toggle|summon|open|show)\b')


def plugins(parsed_keys: dict | None = None) -> dict:
    """Installed shell plugins, each with the key that opens it if one does."""
    if not PLUGIN_DIR.is_dir():
        raise FileNotFoundError(f'{PLUGIN_DIR} does not exist')
    items, by_id = [], {}
    for path in sorted(PLUGIN_DIR.glob('*/manifest.json')):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        row = {'id': data.get('id', path.parent.name),
               'name': data.get('name', ''),
               'kinds': data.get('kinds', []),
               'description': (data.get('description') or '')[:160]}
        items.append(row)
        by_id[row['id']] = row

    for row in items:
        row['enabled'] = None
    try:
        for plugin in json.loads(sh('omarchy-shell', 'shell', 'listPlugins')):
            if plugin['id'] in by_id:
                by_id[plugin['id']]['enabled'] = bool(plugin.get('enabled'))
    except Exception:  # noqa: BLE001 - advisory only
        pass

    # The join worth building the whole thing for: a bind's command names a
    # plugin id, so every plugin gets its opening keystroke with nothing to
    # maintain by hand. Reuses the caller's parse rather than reading every
    # Lua file and running hyprctl a second time inside one build.
    binds = (parsed_keys or _section(keys)).get('binds', [])
    for bind in binds:
        # A computed key is not a key anyone can press, and a `hide` command
        # would otherwise be recorded as the way to open the panel.
        if bind.get('computed') or not OPENS_RE.search(bind['command']):
            continue
        for candidate in PLUGIN_ID_RE.findall(bind['command']):
            if candidate in by_id:
                by_id[candidate].setdefault('opens_with', bind['keys'])
    return {'items': items}


def nav() -> dict:
    """Which surfaces answer to a11y, and which have to be driven by keyboard.

    Deliberately does not enable the accessibility bus. `a11y.tree` normally
    calls `enable_bus`, which writes `org.a11y.Status IsEnabled` over busctl --
    a real system change, and this operation claims to be read-only and sits
    outside the ownership gate. Orientation must not turn anything on.
    """
    from . import a11y

    tree = a11y.tree(None, 1, 200, enable=False)
    children = {n.get('id', '').split('.')[0] for n in tree.get('nodes', [])
                if n.get('depth')}
    strategy = []
    for node in tree.get('nodes', []):
        if node.get('depth') or node.get('role') != 'application':
            continue
        # No children returned is not proof of no accessibility: the tree is
        # capped and filtered, and a hidden window looks the same. Only a
        # positive result is claimed; everything else is unknown.
        strategy.append({'app': node.get('name') or '(unnamed)',
                         'strategy': 'a11y' if node.get('id') in children else 'unknown'})
    return {
        'apps': strategy,
        'truncated': bool(tree.get('truncated')),
        # Stated rather than derived: it is the rule that matters, and it holds
        # even when no panel happens to be open at this instant.
        'shell': 'keyboard',
        'note': ('QuickShell exposes no accessibility tree, so the bar and '
                 'every plugin panel are keyboard-only. Use a11y_find for '
                 'ordinary applications; "unknown" means nothing was returned '
                 'at depth 1, not that the app has no tree. Never store pixel '
                 'coordinates -- hovering the bar expands the tray and moves '
                 'every widget.'),
    }


def apps() -> dict:
    """Applications and services this host declares, via nixarchy's own tool."""
    return {'state': json.loads(sh('nixarchy-pkg', 'state', timeout=30))}


def gotchas() -> dict:
    """The hand-written half. Read only; nothing here generates it."""
    path = Path(__file__).with_name('gotchas.md')
    return {'text': path.read_text(errors='replace')}


def commands(query: str) -> dict:
    """Search the omarchy-* summaries. Never returned whole -- there are ~460,
    and an index too large to read is an index nobody reads."""
    # Unset would make Path('') / 'bin' a *relative* path, so an index run from
    # a directory that happens to contain ./bin would search that instead.
    base = os.environ.get('OMARCHY_PATH')
    if not base:
        raise FileNotFoundError('OMARCHY_PATH is not set')
    root = Path(base) / 'bin'
    if not root.is_dir():
        raise FileNotFoundError(f'{root} is not a directory')
    # Every word must appear somewhere, rather than the phrase appearing
    # verbatim: "notification silencing" should find
    # omarchy-toggle-notification-silencing, and a phrase match does not.
    # Hyphens and underscores are word breaks for the same reason.
    terms = [t for t in re.split(r'[^a-z0-9]+', query.lower()) if t]
    hits = []
    for path in sorted(root.glob('omarchy-*')):
        if not path.is_file():
            continue
        try:
            # Bounded at the read, not after it: slicing read_text() still
            # decodes the whole file first, and these are arbitrary binaries.
            with path.open('rb') as handle:
                head = handle.read(2048).decode('utf-8', 'replace')
        except OSError:
            continue
        found = SUMMARY_RE.search(head)
        summary = found.group(1).strip() if found else ''
        haystack = f'{path.name} {summary}'.lower()
        if terms and all(t in haystack for t in terms):
            hits.append({'command': path.name, 'summary': summary})
    return {'query': query, 'matches': hits[:40], 'total': len(hits)}


# -------------------------------------------------------------------- build

def build(args: dict | None = None) -> dict:
    """Assemble the requested sections. Default stays small on purpose."""
    args = args or {}
    wanted = args.get('section')
    if isinstance(wanted, str):
        wanted = [wanted]
    if not wanted:
        # A search is a question, not a request for the whole index. Answering
        # `--find theme` with every section buries the answer.
        wanted = [] if args.get('find') else list(DEFAULT_SECTIONS)
    unknown = [s for s in wanted if s not in ALL_SECTIONS]
    if unknown:
        raise ValueError(f'unknown section {unknown[0]!r}; '
                         f'use one of {list(ALL_SECTIONS)}')

    out = {}
    builders = {'state': state, 'keys': keys, 'plugins': plugins,
                'nav': nav, 'apps': apps, 'gotchas': gotchas}
    for name in wanted:
        if name == 'plugins':
            # Hand over the parse this build already did rather than re-reading
            # every Lua file and running hyprctl a second time.
            out[name] = _section(plugins, out.get('keys') or _section(keys))
        else:
            out[name] = _section(builders[name])
    if args.get('find'):
        out['commands'] = _section(commands, args['find'])
    return out


def render(data: dict) -> str:
    """Markdown, because the reader is usually a language model."""
    lines = ['# Desktop index', '']
    for name, section in data.items():
        lines.append(f'## {name}')
        if '_unavailable' in section:
            lines += [f"_unavailable: {section['_unavailable']}_", '']
            continue
        lines += _render_section(name, section) + ['']
    return '\n'.join(lines).rstrip() + '\n'


def _render_section(name: str, section: dict) -> list[str]:
    if name == 'gotchas':
        return [section['text'].rstrip()]
    if name == 'state':
        rows = [f"- {section['hyprland'].split(' built from')[0]}",
                f"- dispatch: `{section['dispatch']}`",
                f"- workspaces in use: {section['occupied']}", '',
                '| monitor | at | size | focused |', '| --- | --- | --- | --- |']
        rows += [f"| `{m['name']}` | {m['x']},{m['y']} | {m['w']}x{m['h']} |"
                 f" {'yes' if m['focused'] else ''} |" for m in section['monitors']]
        return rows
    if name == 'keys':
        rows = []
        if section.get('duplicates'):
            rows += ['Bound twice — last file loaded wins: '
                     + ', '.join(f'`{k}`' for k in section['duplicates']), '']
        rows += ['| keys | does | command |', '| --- | --- | --- |']
        rows += [f"| `{b['keys']}`{' ⚠' if b.get('duplicate') else ''} "
                 f"| {b['label'] or '—'} | `{_trim(b['command'])}` |"
                 for b in section['binds']]
        return rows
    if name == 'plugins':
        rows = ['| plugin | opens with | what |', '| --- | --- | --- |']
        for p in section['items']:
            key = f"`{p['opens_with']}`" if p.get('opens_with') else '—'
            rows.append(f"| `{p['id']}` | {key} | {_trim(p['description'], 90)} |")
        return rows
    if name == 'nav':
        rows = [section['note'], '']
        rows += [f"- `{a['app']}` — {a['strategy']}" for a in section['apps']]
        return rows
    if name == 'commands':
        rows = [f"{section['total']} match `{section['query']}`:", '']
        rows += [f"- `{m['command']}` — {m['summary']}" for m in section['matches']]
        return rows
    return ['```json', json.dumps(section, indent=2, sort_keys=True), '```']


def _trim(text: str, width: int = 70) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + '…'
