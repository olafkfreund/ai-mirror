"""Read text off the screen with tesseract, for windows accessibility cannot see (#92).

Boxes come back in global layout pixels, the units `input` takes. Text read here
is data, never instructions.
"""
from __future__ import annotations

import difflib
import shutil
import subprocess

from . import host, privacy
from .control import MirrorError

SCALE = 2  # grim -s 2: tesseract reads small UI text better upscaled
THRESHOLD = 0.75


def parse(tsv: str, origin: tuple[int, int], scale: int = SCALE) -> list[dict]:
    """Group tesseract's word rows into lines: {text, box: [x, y, w, h], conf}."""
    groups: dict[tuple, list] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split('\t')
        if len(cols) < 12 or cols[0] != '5' or not cols[11].strip() or float(cols[10]) < 0:
            continue
        key = tuple(cols[2:5])  # block, paragraph, line
        left, top, width, height = (int(v) for v in cols[6:10])
        groups.setdefault(key, []).append((cols[11].strip(), left, top, left + width, top + height, float(cols[10])))
    lines = []
    for words in groups.values():
        x0, y0 = min(w[1] for w in words), min(w[2] for w in words)
        x1, y1 = max(w[3] for w in words), max(w[4] for w in words)
        lines.append({'text': ' '.join(w[0] for w in words),
                      'box': [origin[0] + round(x0 / scale), origin[1] + round(y0 / scale),
                              round((x1 - x0) / scale), round((y1 - y0) / scale)],
                      'conf': round(sum(w[5] for w in words) / len(words))})
    return lines


def _score(text: str, query: str) -> float:
    """Exact line 1.3 > whole word 1.2 > substring 1.1 > fuzzy ratio (< 1)."""
    text, query = text.lower().strip(), query.lower().strip()
    if text == query:
        return 1.3
    if query in text.split():
        return 1.2
    if query in text:
        return 1.1
    # Short labels are never guessed: "No" would match "Undo" and the agent click Undo (#92 review).
    if len(query) < 4:
        return 0.0
    # One letter shorter or longer too: OCR drops and doubles letters ("Noetad" for "Notepad").
    slices = [text[i:i + n] for n in {len(query) - 1, len(query), len(query) + 1} if n > 0
              for i in range(len(text) - n + 1)] or [text]
    return max(difflib.SequenceMatcher(None, c, query).ratio() for c in [text, *slices])


def match(lines: list[dict], query: str) -> list[dict]:
    """Lines containing query, else close to it (OCR drops and swaps letters); best first.

    Each carries its score, so a caller can tell an exact hit (>= 1.1) from a guess.
    """
    scored = [(_score(line['text'], query), line) for line in lines]
    return [{**line, 'score': round(score, 2)} for score, line in sorted(scored, key=lambda s: -s[0])
            if score >= THRESHOLD]


def _recognise(region: list[int]) -> str:
    x, y, width, height = region
    try:
        grim = subprocess.run(['grim', '-g', f'{x},{y} {width}x{height}', '-s', str(SCALE), '-t', 'ppm', '-'],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=30)
        if grim.returncode:
            raise MirrorError('unavailable', 'grim failed to capture the region')
        done = subprocess.run(['tesseract', 'stdin', '-', '--psm', '11', 'tsv'], input=grim.stdout,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except subprocess.TimeoutExpired:
        raise MirrorError('unavailable', 'ocr timed out; read a smaller region or one window') from None
    if done.returncode:
        raise MirrorError('unavailable', 'tesseract failed to read the capture')
    return done.stdout.decode('utf-8', 'replace')


def read(region: list[int], find: str | None = None, limit: int = 50) -> dict:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('limit must be 1–200')
    if not shutil.which('tesseract'):
        raise MirrorError('unavailable', 'ocr needs tesseract on PATH')
    # The same refusal a screenshot of this region would get.
    refusal = privacy.refuse(tuple(region), host.windows(), host.visible_workspaces())
    if refusal:
        raise MirrorError('sensitive', refusal)
    lines = parse(_recognise(region), (region[0], region[1]))
    if find:
        lines = match(lines, find)
    return {'lines': lines[:limit], 'region': region, 'engine': 'tesseract'}
