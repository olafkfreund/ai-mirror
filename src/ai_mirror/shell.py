"""What the Omarchy shell reports about itself (#99). Only the (target, function)
pairs in READS are ever sent to `qs ipc`, with no arguments: nothing a caller
passes reaches the argv, and no name here changes state."""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import privacy

READS = {  # field -> (target, function); no arguments, ever
    'panels':        ('shell', 'openPanels'),
    'notifications': ('notifications', 'count'),
    'dnd':           ('notifications', 'isDnd'),
    'meeting':       ('meeting-mode', 'status'),
    'idle':          ('idle', 'status'),
    'locked':        ('lock', 'isLocked'),
    'nightlight':    ('nightlight', 'status'),
    'osd':           ('osd', 'state'),
    'monitors':      ('omarchy.monitor', 'state'),
    'rebuild':       ('nixarchy.rebuild.bar', 'status'),
    'media':         ('media', 'status'),
}
UNAVAILABLE = 'unavailable'
# The keys meeting-mode reported on p620 (2026-11-02); a key added later is dropped, not passed on.
MEETING = ('active', 'forced', 'suppressed', 'reason', 'updated', 'call', 'callDetected',
           'callApp', 'callTitle', 'callSince', 'since', 'pausedMedia')


def _instance() -> int | None:
    """The Quickshell on this session's display, or None if there is not exactly one."""
    try:
        out = subprocess.run(['qs', 'list', '--all'], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, errors='replace', timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    want = f'wayland/{os.environ.get("WAYLAND_DISPLAY", "")}'
    found = []
    for block in re.split(r'(?m)^Instance ', out)[1:]:
        pid = re.search(r'^\s*Process ID:\s*(\d+)', block, re.M)
        display = re.search(r'^\s*Display connection:\s*(\S+)', block, re.M)
        if pid and display and display.group(1) == want:
            found.append(int(pid.group(1)))
    return found[0] if len(found) == 1 else None


def _call(pid: int, target: str, function: str) -> str:
    run = subprocess.run(['qs', 'ipc', '--pid', str(pid), 'call', target, function],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace', timeout=2)
    if run.returncode != 0 or not run.stdout.strip():
        raise RuntimeError(f'{target} {function} gave no answer')
    return run.stdout


def _parse(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    if text in ('true', 'on'):
        return True
    if text in ('false', 'off'):
        return False
    return int(text) if text.isdigit() else text


def _media(v):
    if not isinstance(v, dict):
        return UNAVAILABLE
    return {'player': v.get('identity'), 'playing': bool(v.get('playing'))}


def _meeting(v):
    if not isinstance(v, dict):
        return UNAVAILABLE
    kept = {k: v[k] for k in MEETING if k in v}
    found = privacy.kind(str(v.get('callApp') or ''), str(v.get('callTitle') or ''))
    return {**kept, 'callTitle': f'<withheld: {found}>'} if found else kept


REDUCE = {'media': _media, 'meeting': _meeting}


def state() -> dict:
    pid = _instance()
    if pid is None:
        return {**dict.fromkeys(READS, UNAVAILABLE), 'note': 'no Quickshell instance on this display'}
    out, hung = {}, False
    for field, (target, function) in READS.items():
        if hung:  # one timeout means the shell is stuck: 2 s each for the rest would stall the caller
            out[field] = UNAVAILABLE
            continue
        try:
            out[field] = REDUCE.get(field, lambda v: v)(_parse(_call(pid, target, function)))
        except subprocess.TimeoutExpired:
            hung, out[field] = True, UNAVAILABLE
        except Exception:
            out[field] = UNAVAILABLE
    return out
