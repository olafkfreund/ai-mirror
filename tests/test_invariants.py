"""Regression suite for host control. Needs no Wayland session."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import a11y, api, control, guard, host, index, input, mcp, privacy, wait

LAYOUT = [{'name': 'DP-2', 'x': 0, 'y': 0, 'w': 2560, 'h': 1440, 'scale': 1, 'focused': False},
          {'name': 'DP-1', 'x': 2560, 'y': 0, 'w': 2560, 'h': 1440, 'scale': 1, 'focused': False},
          {'name': 'HDMI-A-1', 'x': 1849, 'y': 1440, 'w': 1920, 'h': 1080, 'scale': 1, 'focused': True}]


class FakeHelper(control.Helper):
    """Records lines; acks from a script (default OK)."""

    def __init__(self, acks=None, origin=(0, 0), on_cmd=None):
        super().__init__()
        self.sent, self.acks, self.on_cmd = [], list(acks or []), on_cmd
        self.origin = origin

    def start(self):
        pass

    @property
    def running(self):
        return True

    def cmd(self, line, timeout=15.0):
        self.sent.append(line)
        if self.on_cmd:
            self.on_cmd(line)
        ack = self.acks.pop(0) if self.acks else 'OK'
        if isinstance(ack, Exception):
            raise ack
        return ack


def bus_result(returncode=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def grant(by='agent'):
    """Ask for control and answer yes, as the human does from the bar dialog."""
    return control.confirm_request(control.set_owner('agent', by)['request']['id'])


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp.name})
        env.start()
        self.addCleanup(env.stop)
        # The seams that would change the real desktop refuse from here. A test
        # that genuinely needs one calls guard.disarm().
        guard.arm()
        self.addCleanup(guard.disarm)
        # set_owner('agent') enables accessibility, so every test that takes
        # control would otherwise write org.a11y.Status on the real session
        # bus. 584d8ee fixed the same shape of bug for the desktop.
        self.bus = {'IsEnabled': False, 'ScreenReaderEnabled': False}
        self.bus_writes = []
        stub = patch.object(a11y, '_busctl', self.fake_busctl)
        stub.start()
        self.addCleanup(stub.stop)
        a11y._enabled = False
        a11y._restore.clear()
        self.addCleanup(a11y._restore.clear)
        self.addCleanup(setattr, a11y, '_enabled', False)

    def fake_busctl(self, verb, prop, *value):
        if verb == 'get-property':
            return bus_result(stdout=f"b {'true' if self.bus.get(prop) else 'false'}")
        self.bus_writes.append((prop, value[-1]))
        self.bus[prop] = value[-1] == 'true'
        return bus_result()


class ControlTests(Base):
    def test_generation_bumps_both_ways_and_gates_input(self):
        with self.assertRaises(control.MirrorError) as off:
            control.require_agent(0)
        self.assertEqual(off.exception.code, 'not_owner')
        asked = control.set_owner('agent', 'human')
        self.assertEqual(asked['owner'], 'pending')
        on = control.confirm_request(asked['request']['id'])
        control.require_agent(on['generation'])
        with self.assertRaises(control.MirrorError) as stale:
            control.require_agent(on['generation'] - 1)
        self.assertEqual(stale.exception.code, 'stale_generation')
        off_state = control.set_owner('off', 'human')
        self.assertEqual(off_state['generation'], on['generation'] + 1)
        self.assertIsNone(off_state['enabled_by'])
        self.assertEqual(on['enabled_by'], 'human-confirmed')
        with self.assertRaises(ValueError):
            control.set_owner('human', 'human')

    def test_ownership_rechecked_between_every_line(self):
        gen = grant()['generation']
        helper = FakeHelper(on_cmd=lambda line: line == 'M 1 1' and control.set_owner('off', 'human'))
        with self.assertRaises(control.MirrorError) as err:
            control.run_batch(['M 1 1', 'M 2 2'], gen, helper)
        self.assertEqual(err.exception.code, 'stale_generation')
        self.assertEqual(helper.sent, ['M 1 1', 'C'])

    def test_bug1_helper_error_mid_batch_releases_held_input(self):
        gen = grant()['generation']
        for failure in ('ERR bad move', RuntimeError('helper exited mid-batch')):
            helper = FakeHelper(acks=['OK', failure])
            with self.assertRaises(control.MirrorError):
                control.run_batch(['B 272 1', 'M 5 5', 'B 272 0'], gen, helper)
            self.assertEqual(helper.sent, ['B 272 1', 'M 5 5', 'C'])

    def test_moves_are_offset_by_layout_origin(self):
        gen = grant()['generation']
        helper = FakeHelper(origin=(-1920, 0))
        control.run_batch(['M 0 10', 'K 30 1'], gen, helper)
        self.assertEqual(helper.sent, ['M 1920 10', 'K 30 1'])

    def test_kill_switch_signals_registered_servers_and_skips_stale(self):
        child = subprocess.Popen([sys.executable, '-c', 'import signal,time\nsignal.pause()'])
        self.addCleanup(child.kill)
        time.sleep(0.2)
        control.atomic_write_json(control.servers_dir() / f'{child.pid}.json',
                                  {'pid': child.pid, 'start': control.proc_start(child.pid)})
        stale = control.servers_dir() / '999999.json'
        control.atomic_write_json(stale, {'pid': 999999, 'start': 'x'})
        grant()
        control.set_owner('off', 'human')
        self.assertEqual(child.wait(timeout=5), -signal.SIGUSR1)
        self.assertFalse(stale.exists())

    def test_layout_box_spans_gapped_monitors(self):
        self.assertEqual(host.layout_box(LAYOUT), (0, 0, 5120, 2520))


class ConfirmGate(Base):
    """#10: control is a request a human answers, not a switch an agent throws."""

    def ask(self, by='agent'):
        state = control.set_owner('agent', by)
        return state['request']['id']

    def test_asking_for_control_does_not_take_it(self):
        state = control.set_owner('agent', 'agent')
        self.assertEqual(state['owner'], 'pending')
        with self.assertRaises(control.MirrorError) as err:
            control.require_agent(state['generation'])
        self.assertEqual(err.exception.code, 'not_owner')

    def test_a_bar_click_asks_too_so_one_path_grants_control(self):
        state = control.set_owner('agent', 'human')
        self.assertEqual(state['owner'], 'pending')
        self.assertEqual(state['request']['by'], 'human')

    def test_confirming_the_request_grants_control(self):
        request = self.ask()
        granted = control.confirm_request(request)
        self.assertEqual(granted['owner'], 'agent')
        self.assertEqual(granted['enabled_by'], 'human-confirmed')
        self.assertEqual(granted['request_by'], 'agent')
        control.require_agent(granted['generation'])

    def test_denying_the_request_leaves_control_off(self):
        request = self.ask()
        self.assertEqual(control.deny_request(request)['owner'], 'off')
        with self.assertRaises(control.MirrorError) as err:
            control.require_agent(0)
        self.assertEqual(err.exception.code, 'not_owner')

    def test_a_wrong_answered_or_expired_id_is_refused(self):
        request = self.ask()
        for wrong in ('', 'deadbeefdeadbeef'):
            with self.assertRaises(control.MirrorError) as err:
                control.confirm_request(wrong)
            self.assertEqual(err.exception.code, 'bad_request')
        control.confirm_request(request)
        with self.assertRaises(control.MirrorError) as again:
            control.confirm_request(request)
        self.assertEqual(again.exception.code, 'bad_request')
        control.set_owner('off', 'human')
        expired = self.ask()
        with patch.object(control, 'now', lambda: time.time() + control.REQUEST_TTL + 1):
            with self.assertRaises(control.MirrorError) as late:
                control.confirm_request(expired)
        self.assertEqual(late.exception.code, 'bad_request')

    def test_an_agent_cannot_answer_its_own_request(self):
        request = self.ask()
        for mode in ('confirm', 'deny'):
            with self.assertRaises(control.MirrorError) as err:
                api.run('control', {'mode': mode, 'id': request}, by='agent')
            self.assertEqual(err.exception.code, 'not_owner')
        self.assertEqual(control.read_state()['owner'], 'pending')
        self.assertNotIn('confirm', mcp.SPECS['control']['inputSchema']['properties']['mode']['enum'])
        self.assertNotIn('id', mcp.SPECS['control']['inputSchema']['properties'])

    def test_an_unanswered_request_expires_on_its_own(self):
        self.ask()
        with patch.object(control, 'now', lambda: time.time() + control.REQUEST_TTL + 1):
            self.assertEqual(control.read_state()['owner'], 'off')
        self.assertEqual(control.read_state()['owner'], 'off')
        self.assertNotIn('request', control.read_state())

    def test_a_request_nobody_can_see_names_the_widget(self):
        self.ask()
        with patch.object(control, 'now', lambda: time.time() + control.REQUEST_TTL + 1):
            lapsed = control.read_state()
        self.assertIn('bar widget', lapsed['why'])
        with self.assertRaises(control.MirrorError) as err:
            control.require_agent(lapsed['generation'])
        self.assertIn('olafkfreund.ai-mirror', str(err.exception))

    def test_a_grant_nobody_uses_ends(self):
        granted = control.confirm_request(self.ask())
        with patch.object(control, 'now', lambda: time.time() + control.IDLE_LIMIT + 1):
            with self.assertRaises(control.MirrorError) as err:
                control.require_agent(granted['generation'])
        self.assertEqual(err.exception.code, 'not_owner')
        self.assertEqual(control.read_state()['owner'], 'off')

    def test_using_the_grant_keeps_it_alive(self):
        granted = control.confirm_request(self.ask())
        later = time.time() + control.IDLE_LIMIT - 10
        with patch.object(control, 'now', lambda: later):
            control.run_batch(['M 1 1'], granted['generation'], FakeHelper())
        with patch.object(control, 'now', lambda: later + control.IDLE_LIMIT - 10):
            control.require_agent(granted['generation'])

    def test_turning_control_off_withdraws_a_pending_request(self):
        request = self.ask()
        off = control.set_owner('off', 'human')
        self.assertEqual(off['owner'], 'off')
        self.assertNotIn('request', off)
        with self.assertRaises(control.MirrorError) as err:
            control.confirm_request(request)
        self.assertEqual(err.exception.code, 'bad_request')

    def test_an_agent_that_looks_is_visible_in_the_bar(self):
        watching = control.root() / 'watching'
        api.run('index', {'sections': ['gotchas']}, by='human')
        self.assertFalse(watching.exists())
        api.run('index', {'sections': ['gotchas']}, by='agent')
        self.assertTrue(watching.exists())

    def test_every_decision_leaves_an_audit_line(self):
        control.deny_request(self.ask())
        control.confirm_request(self.ask())
        control.set_owner('off', 'human')
        lines = [json.loads(line) for line in (control.root() / 'audit.jsonl').read_text().splitlines()]
        self.assertEqual([row['event'] for row in lines],
                         ['requested', 'denied', 'requested', 'confirmed', 'off'])
        self.assertTrue(all(row.get('at') for row in lines))

class InputTests(unittest.TestCase):
    def test_encoder_basics_and_limits(self):
        self.assertEqual(input.encode([{'type': 'click', 'x': 10, 'y': 20},
                                       {'type': 'key', 'keys': ['CTRL', 'A']},
                                       {'type': 'type', 'text': 'Hi Ω\nx'}]),
                         ['M 10 20', 'B 272 1', 'B 272 0', 'K 29 1', 'K 30 1', 'K 30 0', 'K 29 0',
                          'T Hi Ω', 'K 28 1', 'K 28 0', 'T x'])
        for bad in ([{'type': 'click', 'x': '10', 'y': 20}], [{'type': 'key', 'keys': ['BOGUS']}],
                    [], [{'type': 'click', 'x': 1, 'y': 2}] * 17, [{'type': 'nope'}]):
            with self.assertRaises(ValueError):
                input.encode(bad)

    def test_bug2_every_coordinate_rejects_negatives(self):
        for bad in ({'type': 'drag', 'x': 10, 'y': 10, 'to_x': -5, 'to_y': 10},
                    {'type': 'drag', 'x': 10, 'y': 10, 'path': [[1, 1], [2, -1]]},
                    {'type': 'drag', 'x': 10, 'y': 10, 'path': [[1, '1']]},
                    {'type': 'mouse_down', 'x': -1, 'y': 0},
                    {'type': 'scroll', 'dy': 1, 'x': 0, 'y': -3}):
            with self.assertRaises(ValueError):
                input.encode([bad])

    def test_full_input_model(self):
        self.assertEqual(input.encode([{'type': 'click', 'x': 1, 'y': 2, 'modifiers': ['SHIFT'], 'count': 3}]),
                         ['K 42 1', 'M 1 2'] + ['B 272 1', 'B 272 0'] * 3 + ['K 42 0'])
        self.assertEqual(input.encode([{'type': 'drag', 'x': 0, 'y': 0, 'path': [[5, 5], [9, 9]], 'button': 'right'}]),
                         ['M 0 0', 'B 273 1', 'M 5 5', 'M 9 9', 'B 273 0'])
        self.assertEqual(input.encode([{'type': 'key_down', 'keys': ['ctrl']}, {'type': 'mouse_up'}]),
                         ['K 29 1', 'B 272 0'])
        self.assertEqual(input.encode([{'type': 'scroll', 'dy': 3}]), ['S 0 3'])
        with self.assertRaises(ValueError):
            input.encode([{'type': 'type', 'text': 'x' * 2000}] * 2 + [{'type': 'click', 'x': 1, 'y': 1, 'count': 3}] * 10)

    def test_key_table(self):
        expected = {'CAPSLOCK': 58, 'F24': 194, 'F13': 183, 'KP0': 82, 'PRINT': 99, 'KEY_SLASH': 53,
                    '/': 53, 'super': 125, 'PLAYPAUSE': 164, 'ESC': 1, 'DELETE': 111, 'F11': 87, 'SPACE': 57}
        self.assertEqual({k: input.key_code(k) for k in expected}, expected)


class HostTests(unittest.TestCase):
    def test_window_dispatch_is_injection_safe(self):
        a = '0x55d1c2a3'
        self.assertEqual(host.window_dispatch('close', a), 'hl.dsp.window.close({ window = "address:0x55d1c2a3" })')
        self.assertEqual(host.window_dispatch('workspace', a, workspace='special:scratch'),
                         'hl.dsp.window.move({ window = "address:0x55d1c2a3", workspace = "special:scratch", follow = false })')
        self.assertEqual(host.window_dispatch('resize', a, w=800, h=600),
                         'hl.dsp.window.resize({ window = "address:0x55d1c2a3", x = 800, y = 600, relative = false })')
        for bad in (('close', '0x1" }) os.execute("rm")'), ('workspace', a, '1"})'), ('resize', a, None, '800', 600),
                    ('fullscreen', a, None, None, None, 'evil'), ('explode', a)):
            with self.assertRaises(ValueError):
                host.window_dispatch(*bad)


class McpTests(Base):
    def test_frame_maps_second_monitor_and_rejects_outside(self):
        frame = {'generation': 4, 'region': [2560, 0, 2560, 1440], 'width': 1280, 'height': 720}
        with patch.dict(mcp.FRAMES, {'f': frame}, clear=True):
            request = {'frame': 'f', 'actions': [{'type': 'drag', 'x': 1279, 'y': 0, 'path': [[640, 360]]}]}
            mapped = mcp.from_frame(request)
            self.assertEqual(mapped['actions'][0], {'type': 'drag', 'x': 5118, 'y': 0, 'path': [[3840, 720]]})
            self.assertEqual(mapped['generation'], 4)
            self.assertEqual(request['actions'][0]['x'], 1279)
            for bad in ({**request, 'generation': 3}, {**request, 'frame': 'missing'},
                        {**request, 'actions': [{'type': 'click', 'x': 1280, 'y': 0}]}):
                with self.assertRaises(ValueError):
                    mcp.from_frame(bad)

    def test_bug4_unexpected_errors_never_kill_the_server(self):
        with patch.object(api, 'run', side_effect=KeyError('boom')):
            result = mcp.handle(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                            'params': {'name': 'windows', 'arguments': {}}}))
        self.assertTrue(result['result']['isError'])
        with patch.object(mcp, 'dispatch', side_effect=AssertionError('x')):
            result = mcp.handle('{"jsonrpc":"2.0","id":2,"method":"ping"}')
        self.assertEqual(result['error']['code'], -32603)
        self.assertEqual(mcp.handle('{"jsonrpc":"2.0","id":3,"method":"missing"}')['error']['code'], -32601)

    def test_input_needs_agent_control(self):
        result = mcp.call_tool('input', {'generation': 0, 'actions': [{'type': 'key', 'keys': ['A']}]})
        self.assertTrue(result['isError'])
        self.assertIn('not_owner', result['content'][0]['text'])
        self.assertTrue(mcp.call_tool('input', {'actions': [], 'bogus': 1})['isError'])

    def test_clipboard_daemon_never_inherits_the_jsonrpc_stdout(self):
        grant()
        with patch.object(api.subprocess, 'run') as run:
            api.run('clipboard', {'action': 'write', 'text': 'x'}, by='agent')
        self.assertIs(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
        control.set_owner('off', 'human')
        with self.assertRaises(control.MirrorError):
            api.run('clipboard', {'action': 'write', 'text': 'x'}, by='agent')

    def test_stdio_lists_tools_and_agent_grant_ends_with_server(self):
        requests = [{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
                    {'method': 'notifications/initialized'},
                    {'id': 2, 'method': 'tools/list'},
                    {'id': 3, 'method': 'tools/call', 'params': {'name': 'control', 'arguments': {'mode': 'agent'}}}]
        data = '\n'.join(json.dumps({'jsonrpc': '2.0', **r}) for r in requests) + '\n'
        result = subprocess.run([str(Path(__file__).resolve().parents[1] / 'bin/ai-mirror'), 'mcp'],
                                input=data, text=True, capture_output=True, check=True)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]['result']['protocolVersion'], '2025-11-25')
        self.assertEqual({t['name'] for t in rows[1]['result']['tools']}, set(mcp.SPECS))
        self.assertEqual(json.loads(rows[2]['result']['content'][0]['text'])['owner'], 'pending')
        self.assertEqual(control.read_state()['owner'], 'off')
        self.assertEqual(list(control.servers_dir().iterdir()), [])
        self.assertEqual(result.stderr, '')


class DesktopIndex(Base):
    """The index parses this host's config shapes and never dies on one source."""

    LUA = """
-- a plain bind
o.bind("SUPER + ALT + N", "nixarchy packages", "omarchy-shell shell toggle nixarchy.pkg '{}'")
-- a bare function reference where the command goes
o.bind("SUPER + CTRL + G", "Reclaim windows", grab_rogue_windows)
-- an inline function, with a comma inside it
o.bind("SUPER + CTRL + LEFT", "Previous workspace", function()
  cycle_group(-1, "a, b")
end)
-- a computed key: unresolvable without running the config
for _, key in ipairs(keys) do
  o.bind("SUPER + " .. key, "Workspace " .. group, function() focus_group(group) end)
end
-- no label at all
o.bind("SUPER + SHIFT + S", nil, "omarchy-capture-screenshot")
"""

    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'bindings.lua').write_text(text)
            with patch.object(index, 'HYPR_DIR', Path(tmp)):
                return index.keys()

    def test_every_bind_form_is_parsed_not_only_the_quoted_one(self):
        # A regex over the quoted form alone dropped 14 of 36 binds on a real
        # host, including every workspace movement key.
        binds = self.parse(self.LUA)['binds']
        self.assertEqual(len(binds), 5)
        by_label = {b['label']: b for b in binds}
        self.assertEqual(by_label['nixarchy packages']['keys'], 'SUPER + ALT + N')
        self.assertIn('nixarchy.pkg', by_label['nixarchy packages']['command'])
        self.assertEqual(by_label['Reclaim windows']['command'], '<grab_rogue_windows>')
        # a comma inside the function body must not end the argument
        self.assertEqual(by_label['Previous workspace']['command'], '<lua function>')

    def test_a_computed_key_is_reported_not_dropped(self):
        binds = self.parse(self.LUA)['binds']
        computed = [b for b in binds if b['computed']]
        self.assertEqual(len(computed), 1)
        self.assertEqual(computed[0]['keys'], 'SUPER + <key>')

    def test_a_nil_label_is_blank_rather_than_the_word_nil(self):
        binds = self.parse(self.LUA)['binds']
        row = [b for b in binds if b['keys'] == 'SUPER + SHIFT + S'][0]
        self.assertEqual(row['label'], '')

    def test_two_binds_on_one_combo_are_flagged(self):
        # Whichever file loads last wins, so presenting one row as the truth
        # would be wrong. SUPER + H is bound twice on a real host.
        duplicated = self.LUA + '\no.bind("SUPER + ALT + N", "something else", "other")\n'
        out = self.parse(duplicated)
        self.assertEqual(out['duplicates'], ['SUPER + ALT + N'])
        self.assertTrue(all(b.get('duplicate') for b in out['binds']
                            if b['keys'] == 'SUPER + ALT + N'))

    def test_a_plugin_gets_the_key_that_opens_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hypr').mkdir()
            (root / 'hypr' / 'bindings.lua').write_text(self.LUA)
            (root / 'plugins' / 'nixarchy.pkg').mkdir(parents=True)
            (root / 'plugins' / 'nixarchy.pkg' / 'manifest.json').write_text(
                json.dumps({'id': 'nixarchy.pkg', 'name': 'Packages',
                            'kinds': ['menu'], 'description': 'search nixpkgs'}))
            with patch.object(index, 'HYPR_DIR', root / 'hypr'), \
                 patch.object(index, 'PLUGIN_DIR', root / 'plugins'):
                items = index.plugins()['items']
        self.assertEqual(items[0]['opens_with'], 'SUPER + ALT + N')

    def test_a_broken_source_degrades_that_section_only(self):
        with patch.object(index, 'HYPR_DIR', Path('/nonexistent')), \
             patch.object(index, 'state', side_effect=RuntimeError('hyprctl gone')):
            out = index.build({'section': ['state', 'gotchas']})
        self.assertIn('_unavailable', out['state'])
        self.assertIn('hyprctl gone', out['state']['_unavailable'])
        self.assertNotIn('_unavailable', out['gotchas'])

    def test_an_unknown_section_is_rejected_by_name(self):
        with self.assertRaises(ValueError) as caught:
            index.build({'section': ['nonsense']})
        self.assertIn('nonsense', str(caught.exception))

    def test_find_answers_only_the_question(self):
        # Returning every section alongside the matches buries the answer.
        with patch.object(index, 'commands', return_value={'query': 'x', 'matches': [], 'total': 0}):
            self.assertEqual(list(index.build({'find': 'x'})), ['commands'])

    def test_gotchas_are_shipped_beside_the_module(self):
        # flake.nix installs the package directory wholesale, so a data file
        # inside it needs no packaging change -- but it must actually be there.
        self.assertTrue(index.gotchas()['text'].strip())

    def test_the_default_payload_stays_small_enough_to_read(self):
        # An index too expensive to read at the start of a session is an index
        # that stops being read. Rendered through build() so this measures the
        # real default path rather than a payload invented by the test.
        with tempfile.TemporaryDirectory() as tmp:
            hypr, plug = Path(tmp) / 'hypr', Path(tmp) / 'plugins'
            hypr.mkdir()
            plug.mkdir()
            hypr.joinpath('b.lua').write_text(
                '\n'.join(f'o.bind("SUPER + {i}", "label {i}", "cmd-{i}")' for i in range(60)))
            for i in range(30):
                d = plug / f'vendor.p{i}'
                d.mkdir()
                d.joinpath('manifest.json').write_text(json.dumps(
                    {'id': f'vendor.p{i}', 'name': f'P{i}', 'kinds': ['menu'],
                     'description': 'x' * 200}))
            with patch.object(index, 'HYPR_DIR', hypr), \
                 patch.object(index, 'PLUGIN_DIR', plug), \
                 patch.object(index, 'state', side_effect=RuntimeError('no compositor')), \
                 patch.object(index, 'nav', side_effect=RuntimeError('no bus')):
                rendered = index.render(index.build({}))
        self.assertLess(len(rendered), 20000, f'default payload is {len(rendered)} bytes')

    def test_a_commented_out_bind_is_not_reported_as_live(self):
        # The exact failure this feature exists to prevent: an agent pressing a
        # key the index promised, that nothing is bound to.
        binds = self.parse('-- o.bind("SUPER + A", "gone", "old")\n'
                           '--[[ o.bind("SUPER + Z", "also gone", "old") ]]\n'
                           'o.bind("SUPER + B", "live", "cmd")\n')['binds']
        self.assertEqual([b['keys'] for b in binds], ['SUPER + B'])

    def test_a_long_string_argument_does_not_lose_the_binding(self):
        binds = self.parse('o.bind("SUPER + B", [[a ) label]], "cmd")\n'
                           'o.bind("SUPER + C", [==[nested ]] here]==], "cmd2")\n')['binds']
        self.assertEqual([b['keys'] for b in binds], ['SUPER + B', 'SUPER + C'])
        self.assertIn(')', binds[0]['label'])

    def test_a_hide_binding_is_not_recorded_as_the_way_to_open(self):
        # `... shell hide nixarchy.pkg` names the plugin too, so matching the
        # id alone once labelled the closing key as the opening one.
        with tempfile.TemporaryDirectory() as tmp:
            hypr, plug = Path(tmp) / 'hypr', Path(tmp) / 'plugins'
            hypr.mkdir()
            (plug / 'nixarchy.pkg').mkdir(parents=True)
            (plug / 'nixarchy.pkg' / 'manifest.json').write_text(
                json.dumps({'id': 'nixarchy.pkg', 'name': 'P', 'kinds': [], 'description': ''}))
            hypr.joinpath('b.lua').write_text(
                'o.bind("SUPER + H", "Hide", "omarchy-shell shell hide nixarchy.pkg")\n'
                'o.bind("SUPER + ALT + N", "Open", "omarchy-shell shell toggle nixarchy.pkg")\n')
            with patch.object(index, 'HYPR_DIR', hypr), patch.object(index, 'PLUGIN_DIR', plug):
                item = index.plugins()['items'][0]
        self.assertEqual(item['opens_with'], 'SUPER + ALT + N')

    def test_a_missing_source_is_unavailable_not_an_empty_inventory(self):
        # An empty glob over a directory that does not exist reads as "this
        # host has no keybindings", which is a different and wrong answer.
        with patch.object(index, 'HYPR_DIR', Path('/nonexistent-hypr')):
            out = index.build({'section': ['keys']})
        self.assertIn('_unavailable', out['keys'])

    def test_orientation_does_not_enable_the_accessibility_bus(self):
        # nav() claims to be read-only and runs outside the ownership gate;
        # a11y.tree normally writes org.a11y.Status over busctl.
        from ai_mirror import a11y
        with patch.object(a11y, 'tree', return_value={'nodes': []}) as tree:
            index.nav()
        self.assertIs(tree.call_args.kwargs.get('enable'), False)



class Wait(Base):
    """Confirming a prerequisite, and the three answers kept apart."""

    LAYERS = {'DP-1': {'levels': {'2': [{'namespace': 'nixarchy-pkg-menu'}]}},
              'DP-2': {'levels': {'0': [{'namespace': 'omarchy-background'}]}}}
    CLIENTS = [{'class': 'Google-chrome', 'title': 'nixarchy — Omarchy, vendored'}]

    def hypr(self, payloads):
        """Stub host.ctl; a payload may be an exception to raise."""
        def ctl(*args, **kwargs):
            value = payloads[args[0]]
            if isinstance(value, Exception):
                raise value
            return json.dumps(value)
        return patch.object(host, 'ctl', side_effect=ctl)

    def test_each_predicate_holds_and_does_not(self):
        with self.hypr({'layers': self.LAYERS, 'clients': self.CLIENTS,
                        'activeworkspace': {'id': 8, 'monitor': 'DP-1'},
                        'devices': {'keyboards': [{'active_keymap': 'English (UK)'}]}}):
            for args in ({'layer': 'nixarchy-pkg-menu'},
                         {'window_class': 'Google-chrome'},
                         {'window_title': 'vendored'},
                         {'workspace': 8},
                         {'layout': 'English (UK)'}):
                self.assertEqual(wait.until({**args, 'timeout': 0.2})['result'],
                                 'confirmed', args)
            for args in ({'layer': 'nope'}, {'window_class': 'nope'},
                         {'window_title': 'nope'}, {'workspace': 99},
                         {'layout': 'German'}):
                self.assertEqual(wait.until({**args, 'timeout': 0.2})['result'],
                                 'not_confirmed', args)

    def test_absent_inverts_the_predicate(self):
        with self.hypr({'layers': self.LAYERS}):
            self.assertEqual(wait.until({'layer': 'gone', 'absent': True})['result'],
                             'confirmed')
            self.assertEqual(wait.until({'layer': 'nixarchy-pkg-menu', 'absent': True,
                                         'timeout': 0.2})['result'], 'not_confirmed')

    def test_an_already_true_prerequisite_returns_on_the_first_poll(self):
        # The case an event-based design cannot see at all: nothing transitions,
        # so a listener would wait out the entire timeout.
        with self.hypr({'layers': self.LAYERS}):
            out = wait.until({'layer': 'nixarchy-pkg-menu', 'timeout': 5})
        self.assertEqual(out['polls'], 1)
        self.assertLess(out['waited_ms'], 500)

    def test_a_prerequisite_that_becomes_true_is_noticed_before_the_deadline(self):
        state = {'n': 0}

        def ctl(*args, **kwargs):
            state['n'] += 1
            present = state['n'] >= 3
            return json.dumps({'M': {'levels': {'0': [{'namespace': 'late'}] if present else []}}})

        with patch.object(host, 'ctl', side_effect=ctl):
            out = wait.until({'layer': 'late', 'timeout': 5})
        self.assertEqual(out['result'], 'confirmed')
        self.assertEqual(out['polls'], 3)
        self.assertLess(out['waited_ms'], 1000, 'noticed at the deadline, not on change')

    def test_a_failure_to_look_is_unavailable_and_never_not_confirmed(self):
        # Conflating these makes a caller act on the absence of evidence.
        with self.hypr({'layers': RuntimeError('Hyprland: no such request')}):
            out = wait.until({'layer': 'anything', 'timeout': 5})
        self.assertEqual(out['result'], 'unavailable')
        self.assertIn('no such request', out['reason'])
        self.assertLess(out['waited_ms'], 1000, 'should fail fast, not poll to the deadline')

    def test_exactly_one_predicate_is_required(self):
        for args in ({}, {'layer': 'a', 'monitor': 'b'}):
            with self.assertRaises(ValueError) as caught:
                wait.until(args)
            self.assertIn('exactly one', str(caught.exception))

    def test_timeout_is_clamped(self):
        with self.hypr({'layers': self.LAYERS}):
            started = time.monotonic()
            with patch.object(wait, 'MAX_TIMEOUT', 0.2):
                out = wait.until({'layer': 'nope', 'timeout': 600})
        self.assertEqual(out['result'], 'not_confirmed')
        self.assertLess(time.monotonic() - started, 5)


    def test_the_monitor_predicate(self):
        with patch.object(host, 'monitors', return_value=LAYOUT):
            self.assertEqual(wait.until({'monitor': 'HDMI-A-1'})['result'], 'confirmed')
            self.assertEqual(wait.until({'monitor': 'DP-1', 'timeout': 0.2})['result'],
                             'not_confirmed')

    def test_a_non_finite_timeout_is_rejected_rather_than_waiting_for_ever(self):
        # min(nan, MAX) is nan and nothing is ever >= nan, so an unvalidated
        # nan polls until the process is killed.
        for bad in (float('nan'), float('inf'), -1, 'soon'):
            with self.assertRaises(ValueError):
                wait.until({'layer': 'x', 'timeout': bad})

    def test_timeout_zero_means_look_once(self):
        with self.hypr({'layers': self.LAYERS}):
            started = time.monotonic()
            out = wait.until({'layer': 'nope', 'timeout': 0})
        self.assertEqual(out['result'], 'not_confirmed')
        self.assertEqual(out['polls'], 1, 'zero was swallowed by a falsy default')
        self.assertLess(time.monotonic() - started, 0.5)

    def test_the_deadline_bounds_the_query_too(self):
        # host.ctl allows itself ten seconds; a caller waiting 0.2 must not be
        # held for ten by one slow probe.
        seen = {}

        def ctl(*args, **kwargs):
            seen['timeout'] = kwargs.get('timeout')
            return json.dumps(self.LAYERS)

        with patch.object(host, 'ctl', side_effect=ctl):
            wait.until({'layer': 'nope', 'timeout': 0.2})
        self.assertIsNotNone(seen['timeout'])
        self.assertLessEqual(seen['timeout'], 0.2 + 1e-6)

    def test_a_malformed_reply_is_unavailable_not_confirmed_absence(self):
        # Reporting confident absence from a reply we could not parse is the
        # same mistake as conflating "could not look" with "not there".
        for payloads, args in (({'layers': {'DP-1': {}}}, {'layer': 'x', 'absent': True}),
                               ({'layers': {}}, {'layer': 'x', 'absent': True}),
                               ({'devices': {}}, {'layout': 'x', 'absent': True}),
                               ({'activeworkspace': {}}, {'workspace': 'None'}),
                               ({'clients': {}}, {'window_class': 'x', 'absent': True})):
            with self.hypr(payloads):
                out = wait.until({**args, 'timeout': 0.2})
            self.assertEqual(out['result'], 'unavailable', (payloads, args))

    def test_the_mcp_schema_accepts_a_timeout(self):
        # 'number' was not in TYPES, so every MCP call carrying a timeout died
        # with KeyError before the wait ever ran.
        mcp.validate('wait', {'layer': 'x', 'timeout': 1})
        mcp.validate('wait', {'layer': 'x', 'timeout': 1.5})
        for bad in (True, 'soon', float('nan')):
            with self.assertRaises(ValueError):
                mcp.validate('wait', {'layer': 'x', 'timeout': bad})

    def test_wait_needs_no_control_grant(self):
        control.set_owner('off', 'human')
        with self.hypr({'layers': self.LAYERS}):
            self.assertEqual(api.run('wait', {'layer': 'nixarchy-pkg-menu'}, by='agent')['result'],
                             'confirmed')



class A11yEnablement(Base):
    """#12: the bus is switched on with both properties, and only for the agent."""

    def test_sets_both_properties_not_just_is_enabled(self):
        before = a11y.enable_bus()
        self.assertEqual([prop for prop, _ in self.bus_writes], list(a11y.A11Y_PROPS))
        self.assertEqual(before, {'IsEnabled': False, 'ScreenReaderEnabled': False})

    def test_busctl_failure_is_reported_not_swallowed(self):
        with patch.object(a11y, '_busctl', lambda *a: bus_result(1, stderr='no bus')):
            with self.assertRaises(control.MirrorError) as err:
                a11y.enable_bus()
        self.assertEqual(err.exception.code, 'unavailable')

    def test_control_off_leaves_a_humans_screen_reader_alone(self):
        self.bus.update(IsEnabled=True, ScreenReaderEnabled=True)
        grant('human')
        self.bus_writes.clear()
        control.set_owner('off', 'human')
        self.assertEqual(self.bus_writes, [])

    def test_control_off_restores_only_what_it_switched_on(self):
        self.bus.update(IsEnabled=True, ScreenReaderEnabled=False)
        grant('human')
        self.bus_writes.clear()
        control.set_owner('off', 'human')
        self.assertEqual(self.bus_writes, [('ScreenReaderEnabled', 'false')])

    def test_regrant_keeps_the_first_grants_record(self):
        grant('human')
        first = control.read_state()['a11y_before']
        grant('agent')  # asking again from a live grant must not lose the record
        self.assertEqual(control.read_state()['a11y_before'], first)

    def test_taking_control_survives_a_broken_bus(self):
        with patch.object(a11y, '_busctl', lambda *a: bus_result(1, stderr='no bus')):
            state = grant('human')
        self.assertEqual(state['owner'], 'agent')

    def test_asking_does_not_switch_the_bus_on(self):
        control.set_owner('agent', 'agent')  # #11: asking is not being granted
        self.assertEqual(control.read_state()['owner'], 'pending')
        self.assertEqual(self.bus_writes, [])

    def test_a_denied_request_puts_back_a_live_grant(self):
        grant('human')
        self.bus_writes.clear()
        pending = control.set_owner('agent', 'agent')
        control.deny_request(pending['request']['id'])
        self.assertEqual(self.bus_writes, [(p, 'false') for p in a11y.A11Y_PROPS])


class A11yCoverage(Base):
    """#12: an empty result must not read as an empty screen."""

    @staticmethod
    def accessible(role='frame', name=''):
        return SimpleNamespace(get_role_name=lambda: role, get_name=lambda: name)

    def walk(self, *levels, row=None):
        def _walk(app, depth, enable=True):
            if enable:
                a11y.ensure_enabled()  # the real seam, not a re-implementation
            for index_, level in enumerate(levels):
                yield str(index_), self.accessible(), level, None, None
        return patch.multiple(a11y, _walk=_walk,
                              _node=lambda acc, node_id, Atspi: {'id': node_id, **(row or {'role': 'frame', 'name': ''})})

    def test_frames_only_tree_says_the_tree_is_unavailable(self):
        with self.walk(0, 1, 0, 1):
            result = a11y.tree()
        self.assertFalse(result['content'])
        self.assertEqual(result['visited'], 4)
        self.assertIn('the tree is unavailable', result['note'])

    def test_a_tree_with_depth_carries_no_note(self):
        # #33: depth is not enough -- the deep node must be something a caller
        # could match or act on, which an unnamed grouping is not.
        with self.walk(0, 1, 2, row={'role': 'push button', 'name': 'Place order'}):
            result = a11y.tree()
        self.assertTrue(result['content'])
        self.assertNotIn('note', result)

    def test_empty_find_on_a_frames_only_desktop_is_explained(self):
        with self.walk(0, 1):
            result = a11y.find(role='push button')
        self.assertEqual(result['nodes'], [])
        self.assertIn('the tree is unavailable', result['note'])

    def test_an_empty_find_names_the_applications_that_had_nothing(self):
        def _walk(app, depth, enable=True):
            if enable:
                a11y.ensure_enabled()
            for i, (level, name) in enumerate(((0, 'Google Chrome'), (1, ''),
                                               (0, 'qemu'), (1, ''), (2, 'a menu'))):
                yield ('0' if i < 2 else '2') + ('' if level == 0 else f'.{level}'), \
                      self.accessible(name=name), level, None, None
        with patch.multiple(a11y, _walk=_walk,
                            _node=lambda acc, node_id, Atspi: {'id': node_id}):
            result = a11y.find(role='push button')
        self.assertEqual(result['nodes'], [])
        self.assertIn('Google Chrome', result['note'])
        self.assertNotIn('qemu', result['note'])  # qemu had content; it is not the reason

    def test_a_matched_find_does_not_claim_the_tree_is_empty(self):
        """#13: find breaks at `limit`, so `deep` under-reports what exists."""
        with self.walk(0, 1):   # never reaches CONTENT_DEPTH
            result = a11y.find(role='frame', limit=1)
        self.assertEqual(len(result['nodes']), 1)
        self.assertNotIn('note', result)

    def test_enable_is_paid_once_per_process(self):
        with self.walk(0, 1):
            a11y.tree()
            a11y.tree()
        self.assertEqual([prop for prop, _ in self.bus_writes], list(a11y.A11Y_PROPS))

    def test_a_bare_read_puts_the_bus_back_on_teardown(self):
        with self.walk(0, 1):
            a11y.tree()
        self.assertEqual(self.bus_writes, [(p, 'true') for p in a11y.A11Y_PROPS])
        self.bus_writes.clear()
        a11y.release_bus()
        self.assertEqual(self.bus_writes, [(p, 'false') for p in a11y.A11Y_PROPS])
        a11y.release_bus()  # idempotent
        self.assertEqual(self.bus_writes, [(p, 'false') for p in a11y.A11Y_PROPS])

    def test_release_leaves_an_agents_grant_alone(self):
        grant('human')
        with self.walk(0, 1):
            a11y.tree()
        self.bus_writes.clear()
        a11y.release_bus()
        self.assertEqual(self.bus_writes, [])

    def test_declining_to_enable_writes_nothing(self):
        with self.walk(0, 1):
            a11y.tree(enable=False)
        self.assertEqual(self.bus_writes, [])

class SensitiveWindows(Base):
    """#19: a capture that would include a credential prompt does not happen.

    Base, not TestCase: it arms the guard and isolates XDG_RUNTIME_DIR, and a
    test class in this file that opts out of that is exactly how a test reaches
    the real desktop (#15).
    """

    WINS = [
        {'class': '1Password', 'title': 'Personal Vault', 'at': [2600, 0],
         'size': [800, 600], 'workspace': '4'},
        {'class': 'foot', 'title': 'p620: notes', 'at': [0, 0],
         'size': [800, 600], 'workspace': '4'},
    ]

    def test_class_and_title_are_both_needed(self):
        # a generic title, identified only by class
        self.assertEqual(privacy.kind('gcr-prompter', 'Unlock'), 'a credential prompt')
        # an opaque class, identified only by title -- the web app case
        self.assertEqual(privacy.kind('chrome-abc-Default', 'Revolut - Payments'),
                         'a banking or payment page')
        self.assertIsNone(privacy.kind('foot', 'p620: notes'))

    def test_the_category_is_a_fixed_string_never_the_window(self):
        found = privacy.kind('chrome-x', 'Revolut  someone@example.com  Inbox (7)')
        self.assertIn(found, {c for c, _ in privacy.SENSITIVE})
        self.assertNotIn('someone@example.com', found)

    def test_the_unit_is_the_rectangle_not_the_focused_window(self):
        # the vault is at x=2600; a whole-layout capture includes it
        self.assertTrue(privacy.refuse((0, 0, 5120, 1440), self.WINS, {'4'}))
        # a region that stops short of it does not
        self.assertIsNone(privacy.refuse((0, 0, 800, 600), self.WINS, {'4'}))

    def test_a_window_on_another_workspace_does_not_refuse(self):
        self.assertIsNone(privacy.refuse((0, 0, 5120, 1440), self.WINS, {'9'}))

    def test_the_refusal_names_the_way_forward_and_admits_it_is_a_heuristic(self):
        msg = privacy.refuse((0, 0, 5120, 1440), self.WINS, {'4'})
        self.assertIn('narrower' if 'narrower' in msg else 'specific region', msg)
        self.assertIn('misfires', msg)
        self.assertNotIn('Personal Vault', msg)

    def test_screenshot_raises_the_sensitive_code(self):
        import tempfile
        from pathlib import Path as P
        with patch.object(host, 'windows', lambda: self.WINS), \
             patch.object(host, 'visible_workspaces', lambda: {'4'}), \
             patch.object(host, 'monitor', lambda n=None: {
                 'x': 0, 'y': 0, 'w': 5120, 'h': 1440, 'name': 'DP-1'}):
            with self.assertRaises(control.MirrorError) as err:
                control.screenshot(P(tempfile.mkdtemp()) / 'x.png')
        self.assertEqual(err.exception.code, 'sensitive')

class A11yPrivacy(Base):
    """#20: the tree does not read inside a window it should not read."""

    @staticmethod
    def acc(name, role='frame'):
        return SimpleNamespace(get_name=lambda: name, get_role_name=lambda: role)

    def walk_of(self, app_name, frames):
        """A fake desktop: one application, several frames, guarded as _walk does."""
        def _walk(app, depth, enable=True):
            app_withheld = privacy.kind(app_name, '')
            yield '6', self.acc(app_name, 'application'), 0, None, app_withheld
            if app_withheld:
                return  # _walk does not descend into a refused application
            for i, title in enumerate(frames):
                yield f'6.{i}', self.acc(title), 1, None, privacy.kind(app_name, title)
        return patch.multiple(
            a11y, _walk=_walk,
            _node=lambda acc, node_id, At: {'id': node_id, 'role': acc.get_role_name(),
                                            'name': acc.get_name()})

    def test_a_refused_frame_does_not_cost_its_siblings(self):
        """The Chrome case. Getting this wrong is an outage, not a leak."""
        with self.walk_of('Google Chrome',
                          ['Revolut - Payments', 'GitHub - a repo', 'Docs - a page']):
            nodes = a11y.tree()['nodes']
        kept = [n for n in nodes if n['id'].startswith('6.') and 'withheld' not in n]
        self.assertEqual(len(kept), 2)

    def test_a_refused_frame_carries_the_kind_and_not_the_name(self):
        with self.walk_of('Google Chrome', ['Revolut  someone@example.com']):
            hidden = [n for n in a11y.tree()['nodes'] if 'withheld' in n]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0]['withheld'], 'a banking or payment page')
        self.assertNotIn('name', hidden[0])

    def test_a_sensitive_application_is_refused_whole(self):
        with self.walk_of('1Password', ['Personal Vault']):
            nodes = a11y.tree()['nodes']
        self.assertEqual(len(nodes), 1)          # never descended
        self.assertEqual(nodes[0]['withheld'], 'a password manager')

    def test_find_says_it_withheld_rather_than_implying_absence(self):
        with self.walk_of('Google Chrome', ['Revolut - Payments', 'GitHub']):
            result = a11y.find(name='Revolut')
        self.assertEqual(result['nodes'], [])
        self.assertEqual(result['withheld'], 1)
        self.assertIn('not looked at', result['note'])

    def test_an_ordinary_desktop_is_unchanged(self):
        with self.walk_of('Google Chrome', ['GitHub - a repo']):
            result = a11y.tree()
        self.assertFalse(any('withheld' in n for n in result['nodes']))
        self.assertTrue(all('name' in n for n in result['nodes']))

    def test_act_cannot_reach_inside_a_refused_window(self):
        chain = [self.acc('1Password', 'application'), self.acc('Personal Vault')]

        class Desk:
            def __init__(self): self.i = -1
            def get_child_at_index(self, _i):
                self.i += 1
                return chain[self.i] if self.i < len(chain) else None

        with patch.object(a11y, '_atspi',
                          lambda: SimpleNamespace(get_desktop=lambda n: Desk())):
            with self.assertRaises(control.MirrorError) as err:
                a11y.resolve('3.0')
        self.assertEqual(err.exception.code, 'sensitive')

if __name__ == '__main__':
    unittest.main()
