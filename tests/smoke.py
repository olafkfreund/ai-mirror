"""Live check on the running Hyprland desktop. Run explicitly: python3 tests/smoke.py

It MOVES YOUR MOUSE and types into a terminal it opens itself (foot), then
closes it and turns agent control off. Keep your hands off for ~10 seconds.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sideyard import api, control, mcp

# 100 distinct characters: crosses keycodes that mean F9/Print/volume on real layouts
# (they must never be used for typing) and needs several keymap rounds.
LONG = 'ok Ω ' + ''.join(chr(0x4E00 + i) for i in range(95))


def wait_for(check, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (result := check()):
            return result
        time.sleep(0.1)
    raise AssertionError('Timed out')


def main():
    proof = Path(tempfile.mkdtemp()) / 'proof'
    app_id = f'sideyard-smoke-{os.getpid()}'
    gen = api.run('control', {'mode': 'agent'})['generation']
    window = None
    try:
        # A plain `read`, not the user's shell: slow shell startup discards type-ahead.
        api.run('launch', {'argv': ['foot', '--app-id', app_id, 'sh', '-c', f'IFS= read -r line && printf %s "$line" > {proof}']})
        window = wait_for(lambda: next((w for w in api.run('windows')['windows'] if w.get('class') == app_id), None))
        api.run('window', {'action': 'focus', 'address': window['address']})
        region = window['at'] + window['size']
        # Frame-relative input, exactly as an MCP agent does it.
        frame = mcp.observe({'region': region, 'max_size': 640})
        meta = json.loads(frame[0]['text'])
        assert frame[1]['type'] == 'image' and meta['generation'] == gen
        args = mcp.from_frame({'frame': meta['frame'], 'actions': [
            {'type': 'click', 'x': meta['width'] // 2, 'y': meta['height'] // 2},
            {'type': 'type', 'text': 'discard'}, {'type': 'key', 'keys': ['CTRL', 'U']},
            {'type': 'type', 'text': LONG + '\n'}]})
        api.run('input', args)
        assert wait_for(lambda: proof.exists() and proof.read_text() == LONG), proof.read_text()
        api.run('clipboard', {'action': 'write', 'text': 'sideyard ✓'}, by='agent')
        assert api.run('clipboard', {'action': 'read'})['text'] == 'sideyard ✓'
        # The kill switch path: a separate process revokes, stale input is refused.
        subprocess.run([str(Path(__file__).resolve().parents[1] / 'bin/sideyard'), 'control', 'off'], check=True, capture_output=True)
        try:
            api.run('input', {'generation': gen, 'actions': [{'type': 'key', 'keys': ['A']}]})
            raise AssertionError('input accepted after kill switch')
        except control.AwError as exc:
            assert exc.code in ('not_owner', 'stale_generation'), exc
        print('PASS: launch, windows, focus, frame input, Unicode typing, clipboard, kill switch')
    finally:
        state = control.set_owner('agent', 'human')
        if window and any(w['address'] == window['address'] for w in api.run('windows')['windows']):
            api.run('window', {'action': 'close', 'address': window['address']})
        control.set_owner('off', 'human')
        control.HELPER.stop()
        print('control:', control.read_state()['owner'], '(was generation', state['generation'], ')')


if __name__ == '__main__':
    main()
