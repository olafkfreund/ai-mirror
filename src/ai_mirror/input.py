"""Translate readable input actions to ai-mirror-input helper lines (M/B/S/K/T)."""
import re

# Linux evdev codes 0..127, in order (input-event-codes.h); '_' marks gaps.
_CLASSIC = '''RESERVED ESC 1 2 3 4 5 6 7 8 9 0 MINUS EQUAL BACKSPACE TAB Q W E R T Y U I O P
LEFTBRACE RIGHTBRACE ENTER LEFTCTRL A S D F G H J K L SEMICOLON APOSTROPHE GRAVE LEFTSHIFT
BACKSLASH Z X C V B N M COMMA DOT SLASH RIGHTSHIFT KPASTERISK LEFTALT SPACE CAPSLOCK F1 F2 F3
F4 F5 F6 F7 F8 F9 F10 NUMLOCK SCROLLLOCK KP7 KP8 KP9 KPMINUS KP4 KP5 KP6 KPPLUS KP1 KP2 KP3
KP0 KPDOT _ ZENKAKUHANKAKU 102ND F11 F12 RO KATAKANA HIRAGANA HENKAN KATAKANAHIRAGANA
MUHENKAN KPJPCOMMA KPENTER RIGHTCTRL KPSLASH SYSRQ RIGHTALT LINEFEED HOME UP PAGEUP LEFT
RIGHT END DOWN PAGEDOWN INSERT DELETE MACRO MUTE VOLUMEDOWN VOLUMEUP POWER KPEQUAL
KPPLUSMINUS PAUSE SCALE KPCOMMA HANGEUL HANJA YEN LEFTMETA RIGHTMETA COMPOSE'''.split()
KEYS = {name: code for code, name in enumerate(_CLASSIC) if name != '_'}
KEYS.update({f'F{n}': 170 + n for n in range(13, 25)})  # F13=183 .. F24=194
KEYS.update(STOP=128, AGAIN=129, UNDO=131, COPY=133, OPEN=134, PASTE=135, FIND=136, CUT=137,
            HELP=138, CALC=140, SLEEP=142, WWW=150, MAIL=155, BACK=158, FORWARD=159,
            NEXTSONG=163, PLAYPAUSE=164, PREVIOUSSONG=165, STOPCD=166, REFRESH=173,
            BRIGHTNESSDOWN=224, BRIGHTNESSUP=225, MICMUTE=248)
ALIASES = {'CTRL': 'LEFTCTRL', 'CONTROL': 'LEFTCTRL', 'SHIFT': 'LEFTSHIFT', 'ALT': 'LEFTALT',
           'SUPER': 'LEFTMETA', 'META': 'LEFTMETA', 'WIN': 'LEFTMETA', 'CMD': 'LEFTMETA',
           'ALTGR': 'RIGHTALT', 'ESCAPE': 'ESC', 'RETURN': 'ENTER', 'DEL': 'DELETE', 'INS': 'INSERT',
           'PRINT': 'SYSRQ', 'PRINTSCREEN': 'SYSRQ', 'MENU': 'COMPOSE', 'PGUP': 'PAGEUP',
           'PGDN': 'PAGEDOWN', 'PERIOD': 'DOT', 'QUOTE': 'APOSTROPHE', 'BACKTICK': 'GRAVE',
           '-': 'MINUS', '=': 'EQUAL', '[': 'LEFTBRACE', ']': 'RIGHTBRACE', ';': 'SEMICOLON',
           "'": 'APOSTROPHE', '`': 'GRAVE', '\\': 'BACKSLASH', ',': 'COMMA', '.': 'DOT', '/': 'SLASH'}
KEYS['PRINT'] = KEYS['SYSRQ']
BUTTONS = {'left': 272, 'right': 273, 'middle': 274, 'back': 275, 'forward': 276}
MAX_LINES = 64


def key_code(name) -> int:
    if not isinstance(name, str):
        raise ValueError('key names must be strings')
    upper = name.upper().removeprefix('KEY_')
    upper = ALIASES.get(upper, ALIASES.get(name, upper))
    if upper not in KEYS:
        raise ValueError(f'Unknown key name: {name!r}')
    return KEYS[upper]


def point(action, kx='x', ky='y'):
    """Every coordinate pair is validated here: integers, never negative."""
    x, y = action.get(kx), action.get(ky)
    if type(x) is not int or type(y) is not int:
        raise ValueError(f'{kx} and {ky} must be integers')
    if x < 0 or y < 0:
        raise ValueError('Coordinates cannot be negative')
    return x, y


def _keys(action, field, low, high):
    names = action.get(field, [])
    if not isinstance(names, list) or not low <= len(names) <= high:
        raise ValueError(f'{field} must be an array of {low}–{high} key names, e.g. ["CTRL", "A"]')
    return [key_code(n) for n in names]


def _button(action):
    button = BUTTONS.get(action.get('button', 'left'))
    if button is None:
        raise ValueError(f'button must be one of {", ".join(BUTTONS)}')
    return button


KEYBOARD_KINDS = frozenset({'type', 'key', 'key_down', 'key_up'})


def needs_window(actions) -> bool:
    """Whether this batch types, and so must name the window it types into.

    Read from the ACTIONS, never from the lines `encode` produces. A modifier
    on a pointer action emits `K <mod> 1` (see below), so a ctrl+click looks
    like keyboard input on the wire and is not. Sniffing prefixes would demand
    a window for every modified click.
    """
    if not isinstance(actions, list):
        return False
    return any(isinstance(a, dict) and a.get('type') in KEYBOARD_KINDS for a in actions)


def encode(actions) -> list[str]:
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
        raise ValueError('Provide 1–16 actions per input call')
    lines = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('Each action must be an object')
        kind = action.get('type')
        mods = _keys(action, 'modifiers', 0, 4)
        lines += [f'K {m} 1' for m in mods]
        if kind in ('move', 'click', 'drag'):
            lines.append('M %d %d' % point(action))
            if kind == 'click':
                count = action.get('count', 1)
                if type(count) is not int or count not in (1, 2, 3):
                    raise ValueError('click count must be 1, 2 or 3')
                button = _button(action)
                lines += [f'B {button} 1', f'B {button} 0'] * count
            elif kind == 'drag':
                button = _button(action)
                path = action.get('path')
                if path is None:
                    path = [list(point(action, 'to_x', 'to_y'))]
                if not isinstance(path, list) or not 1 <= len(path) <= 32:
                    raise ValueError('drag needs to_x/to_y or a path of 1–32 [x, y] points')
                lines.append(f'B {button} 1')
                for p in path:
                    if not isinstance(p, list) or len(p) != 2:
                        raise ValueError('path points must be [x, y]')
                    lines.append('M %d %d' % point({'x': p[0], 'y': p[1]}))
                lines.append(f'B {button} 0')
        elif kind in ('mouse_down', 'mouse_up'):
            if 'x' in action or 'y' in action:
                lines.append('M %d %d' % point(action))
            lines.append(f'B {_button(action)} {1 if kind == "mouse_down" else 0}')
        elif kind == 'scroll':
            dx, dy = action.get('dx', 0), action.get('dy', 0)
            if type(dx) is not int or type(dy) is not int or not (dx or dy):
                raise ValueError('scroll needs integer dx and/or dy steps')
            if 'x' in action or 'y' in action:
                lines.append('M %d %d' % point(action))
            lines.append(f'S {dx} {dy}')
        elif kind == 'type':
            value = action.get('text')
            if not isinstance(value, str) or not value:
                raise ValueError('text must be a non-empty string')
            if len(value.encode('utf-8')) > 4096 or any((ord(c) < 32 and c not in '\n\t') or ord(c) == 127 for c in value):
                raise ValueError('Use up to 4096 UTF-8 bytes; only newline and tab control characters are supported')
            for piece in re.split(r'([\n\t])', value):
                if piece in ('\n', '\t'):
                    code = KEYS['ENTER'] if piece == '\n' else KEYS['TAB']
                    lines += [f'K {code} 1', f'K {code} 0']
                elif piece:
                    lines += ['T ' + piece[i:i + 240] for i in range(0, len(piece), 240)]
        elif kind == 'key':
            codes = _keys(action, 'keys', 1, 5)
            lines += [f'K {c} 1' for c in codes] + [f'K {c} 0' for c in reversed(codes)]
        elif kind in ('key_down', 'key_up'):
            lines += [f'K {c} {1 if kind == "key_down" else 0}' for c in _keys(action, 'keys', 1, 5)]
        else:
            raise ValueError(f'Unknown action type: {kind}')
        lines += [f'K {m} 0' for m in reversed(mods)]
    if len(lines) > MAX_LINES:
        raise ValueError('Input batch too large; split into smaller calls')
    return lines
