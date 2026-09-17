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
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in '"\'' and arg[0] not in arg[1:-1]:
        return arg[1:-1], True
    parts = []
    for piece in arg.split('..'):
        piece = piece.strip()
        if len(piece) >= 2 and piece[0] == piece[-1] and piece[0] in '"\'':
            parts.append(piece[1:-1])
        elif piece.startswith('function'):
            parts.append('<lua function>')
        else:
            parts.append(f'<{piece}>')
    return ''.join(parts).strip(), False


def keys() -> dict:
    """Every labelled keybinding, from the Lua that already describes them."""
    binds, files = [], sorted(HYPR_DIR.glob('*.lua'))
    for path in files:
        if '.bak' in path.name or '.decoy' in path.name:
            continue
        text = path.read_text(errors='replace')
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
    out = {'binds': binds, 'files': [p.name for p in files]}
    try:
        # Not a source, a sanity check: thousands of raw binds against a
        # handful of parsed ones means the regex stopped matching.
        out['hyprctl_bind_count'] = len(json.loads(sh('hyprctl', 'binds', '-j')))
    except Exception:  # noqa: BLE001 - advisory only
        pass
    return out


def plugins() -> dict:
    """Installed shell plugins, each with the key that opens it if one does."""
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
    # maintain by hand.
    for bind in _section(keys).get('binds', []):
        for candidate in PLUGIN_ID_RE.findall(bind['command']):
            if candidate in by_id:
                by_id[candidate].setdefault('opens_with', bind['keys'])
    return {'items': items}


def nav() -> dict:
    """Which surfaces answer to a11y, and which are keyboard-only."""
    from . import a11y

    tree = a11y.tree(None, 1, 200)
    apps, seen = [], set()
    for node in tree.get('nodes', []):
        if node.get('depth') or node.get('role') != 'application':
            continue
        name = node.get('name') or '(unnamed)'
        if name in seen:
            continue
        seen.add(name)
        apps.append(name)
    children = {n.get('id', '').split('.')[0] for n in tree.get('nodes', [])
                if n.get('depth')}
    strategy = []
    for node in tree.get('nodes', []):
        if node.get('depth') or node.get('role') != 'application':
            continue
        has_kids = node.get('id') in children
        strategy.append({'app': node.get('name') or '(unnamed)',
                         'strategy': 'a11y' if has_kids else 'keyboard'})
    return {
        'apps': strategy,
        # Stated rather than derived because it is the rule that matters and it
        # holds even when no panel happens to be open at this instant.
        'shell': 'keyboard',
        'note': ('QuickShell exposes no accessibility tree, so the bar and '
                 'every plugin panel are keyboard-only. Use a11y_find for '
                 'ordinary applications; never store pixel coordinates -- '
                 'hovering the bar expands the tray and moves every widget.'),
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
    root = Path(os.environ.get('OMARCHY_PATH', '')) / 'bin'
    if not root.is_dir():
        raise FileNotFoundError('OMARCHY_PATH/bin not found')
    needle, hits = query.lower(), []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        try:
            head = path.read_text(errors='replace')[:2048]
        except OSError:
            continue
        found = SUMMARY_RE.search(head)
        summary = found.group(1).strip() if found else ''
        if needle in path.name.lower() or needle in summary.lower():
            hits.append({'command': path.name, 'summary': summary})
    return {'query': query, 'matches': hits[:40], 'total': len(hits)}


# -------------------------------------------------------------------- build

def build(args: dict | None = None) -> dict:
    """Assemble the requested sections. Default stays small on purpose."""
    args = args or {}
    wanted = args.get('section') or list(DEFAULT_SECTIONS)
    if isinstance(wanted, str):
        wanted = [wanted]
    unknown = [s for s in wanted if s not in ALL_SECTIONS]
    if unknown:
        raise ValueError(f'unknown section {unknown[0]!r}; '
                         f'use one of {list(ALL_SECTIONS)}')

    out = {}
    builders = {'state': state, 'keys': keys, 'plugins': plugins,
                'nav': nav, 'apps': apps, 'gotchas': gotchas}
    for name in wanted:
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
    if name == 'keys':
        rows = ['| keys | does | command |', '| --- | --- | --- |']
        rows += [f"| `{b['keys']}` | {b['label']} | `{_trim(b['command'])}` |"
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
