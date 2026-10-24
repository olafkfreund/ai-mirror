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
from ai_mirror import api, control, mcp

# 100 distinct characters: crosses keycodes that mean F9/Print/volume on real layouts
# (they must never be used for typing) and needs several keymap rounds.
LONG = 'ok Ω ' + ''.join(chr(0x4E00 + i) for i in range(95))


def take_control():
    """Ask for control and answer yes; you are the human this script speaks for."""
    return control.confirm_request(control.set_owner('agent', 'human')['request']['id'])


def wait_for(check, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (result := check()):
            return result
        time.sleep(0.1)
    raise AssertionError('Timed out')


def main():
    proof = Path(tempfile.mkdtemp()) / 'proof'
    app_id = f'ai-mirror-smoke-{os.getpid()}'
    gen = take_control()['generation']
    window = None
    try:
        # A plain `read`, not the user's shell: slow shell startup discards type-ahead.
        api.run('launch', {'generation': gen, 'argv': ['foot', '--app-id', app_id, 'sh', '-c', f'IFS= read -r line && printf %s "$line" > {proof}']})
        window = wait_for(lambda: next((w for w in api.run('windows')['windows'] if w.get('class') == app_id), None))
        api.run('window', {'generation': gen, 'action': 'focus', 'address': window['address']})
        region = window['at'] + window['size']
        # Frame-relative input, exactly as an MCP agent does it.
        frame = mcp.observe({'region': region, 'max_size': 640})
        meta = json.loads(frame[0]['text'])
        assert frame[1]['type'] == 'image' and meta['generation'] == gen
        args = mcp.from_frame({'frame': meta['frame'], 'window': window['address'], 'actions': [
            {'type': 'click', 'x': meta['width'] // 2, 'y': meta['height'] // 2},
            {'type': 'type', 'text': 'discard'}, {'type': 'key', 'keys': ['CTRL', 'U']},
            {'type': 'type', 'text': LONG + '\n'}]})
        api.run('input', args)
        assert wait_for(lambda: proof.exists() and proof.read_text() == LONG), proof.read_text()
        api.run('clipboard', {'generation': gen, 'action': 'write', 'text': 'ai-mirror ✓'}, by='agent')
        assert api.run('clipboard', {'action': 'read'})['text'] == 'ai-mirror ✓'
        # The kill switch path: a separate process revokes, stale input is refused.
        subprocess.run([str(Path(__file__).resolve().parents[1] / 'bin/ai-mirror'), 'control', 'off'], check=True, capture_output=True)
        try:
            api.run('input', {'generation': gen, 'actions': [{'type': 'key', 'keys': ['A']}]})
            raise AssertionError('input accepted after kill switch')
        except control.MirrorError as exc:
            assert exc.code in ('not_owner', 'stale_generation'), exc
        print('PASS: launch, windows, focus, frame input, Unicode typing, clipboard, kill switch')
    finally:
        state = take_control()
        if window and any(w['address'] == window['address'] for w in api.run('windows')['windows']):
            api.run('window', {'generation': state['generation'], 'action': 'close', 'address': window['address']})
        control.set_owner('off', 'human')
        control.HELPER.stop()
        print('control:', control.read_state()['owner'], '(was generation', state['generation'], ')')


def check_index():
    """The index must describe THIS host, not merely fail to raise.

    A parser that quietly returns nothing looks identical to a machine with no
    keybindings, so the assertions are plausible minimums rather than "not
    empty". This is the half that fixtures cannot cover: it reads the real
    config, the real plugin manifests and the real accessibility tree.
    """
    from ai_mirror import index

    data = index.build({})
    broken = {k: v['_unavailable'] for k, v in data.items() if '_unavailable' in v}
    assert not broken, f'sections unavailable: {broken}'

    binds = data['keys']['binds']
    assert len(binds) >= 30, f'only {len(binds)} keybindings parsed'
    raw = data['keys'].get('hyprctl_bind_count')
    assert raw is None or raw > len(binds), 'hyprctl reported fewer binds than the config'

    plugins = data['plugins']['items']
    assert len(plugins) >= 20, f'only {len(plugins)} plugins found'
    opens = [p for p in plugins if p.get('opens_with')]
    assert opens, 'no plugin was joined to the key that opens it'

    # Only the positive claim is testable: something must really expose a
    # tree. Asserting nav['shell'] == 'keyboard' would only re-read a constant
    # this module wrote, which verifies nothing.
    assert any(a['strategy'] == 'a11y' for a in data['nav']['apps']), \
        'no application exposed an accessibility tree'
    assert not data['nav']['truncated'], 'a11y tree truncated; strategies unreliable'

    assert data['gotchas']['text'].strip()

    rendered = index.render(data)
    assert len(rendered) < 22000, f'default payload is {len(rendered)} bytes'
    print(f'PASS: index -- {len(binds)} keys, {len(plugins)} plugins, '
          f'{len(opens)} joined to a key, {len(rendered)} bytes')


def check_wait():
    """Live: the sequence that motivated this, including the negative case.

    A happy-path-only check would not have caught the failure this came from,
    which is precisely a step that did not happen being treated as one that did.
    """
    from ai_mirror import api, control, host, index, wait

    # Any panel this host has will do; the check is of wait, not of one plugin.
    candidates = sorted(
        (p for p in index.plugins()['items']
         if p.get('enabled') is True and p.get('opens_with')
         and {'menu', 'panel'} & set(p.get('kinds') or [])
         and p['id'] != 'olafkfreund.ai-mirror'),
        key=lambda p: p['id'])
    if not candidates:
        print('SKIP: check_wait -- no enabled plugin opens a panel from a key on this host')
        return

    take_control()
    chosen = None
    try:
        gen = control.read_state()['generation']
        subprocess.run(['hyprctl', 'dispatch', 'hl.dsp.focus({ monitor = "DP-1" })'],
                       capture_output=True)
        time.sleep(0.4)

        def press(keys):
            # A global shortcut still names a target since #24: the focused window it lands on.
            *rest, last = keys.split(' + ')
            try:
                api.run('input', {'generation': gen, 'window': host.focused_address(),
                                  'actions': [{'type': 'key', 'keys': [last],
                                               'modifiers': rest}]})
            except control.MirrorError as exc:
                # A fast panel maps between key-down and key-up: the guard then
                # refuses the release and releases held keys itself. The key fired.
                if 'opened since control was granted' not in str(exc):
                    raise

        def hide(plugin_id):
            subprocess.run(['omarchy-shell', '-q', 'shell', 'hide', plugin_id],
                           capture_output=True)

        # Discover the layer namespace: press the key, see what appeared.
        # Never type into a discovered panel; some write configuration.
        ns = None
        for p in candidates:
            before = {l['namespace'] for l in host.layers()}
            try:
                press(p['opens_with'])
                deadline = time.monotonic() + 5
                while ns is None and time.monotonic() < deadline:
                    new = {l['namespace'] for l in host.layers()} - before
                    if new:
                        ns = sorted(new)[0]
                    else:
                        time.sleep(0.1)
            finally:
                hide(p['id'])
            if ns:
                chosen = p
                break
        if not chosen:
            ids = [p['id'] for p in candidates]
            raise AssertionError(f'no panel appeared for {ids}')

        # It is already closing from discovery.
        out = wait.until({'layer': ns, 'absent': True, 'timeout': 5})
        assert out['result'] == 'confirmed', out

        press(chosen['opens_with'])
        out = wait.until({'layer': ns, 'timeout': 5})
        assert out['result'] == 'confirmed', f'panel never appeared: {out}'
        opened_ms = out['waited_ms']

        hide(chosen['id'])
        out = wait.until({'layer': ns, 'absent': True, 'timeout': 5})
        assert out['result'] == 'confirmed', f'panel never closed: {out}'

        # The negative: a prerequisite that will never hold must stop the
        # sequence rather than let it run on.
        # The negative result itself. This asserts what wait returns, not that
        # a caller obeyed it -- obedience is the caller's job and is covered by
        # the acceptance run in the PR, not here.
        out = wait.until({'layer': 'no-such-layer', 'timeout': 1})
        assert out['result'] == 'not_confirmed', out
        assert 900 < out['waited_ms'] < 2000, out

        print(f"PASS: wait -- {chosen['id']} ({ns}) confirmed in {opened_ms} ms, "
              f'close confirmed, absent layer correctly not_confirmed')
    finally:
        if chosen:
            subprocess.run(['omarchy-shell', '-q', 'shell', 'hide', chosen['id']],
                           capture_output=True)
        control.set_owner('off', 'human')
        control.HELPER.stop()


if __name__ == '__main__':
    check_index()
    check_wait()
    main()
