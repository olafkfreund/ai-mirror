"""Regression suite for host control. Needs no Wayland session."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, control, host, input, mcp

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


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp.name})
        env.start()
        self.addCleanup(env.stop)


class ControlTests(Base):
    def test_generation_bumps_both_ways_and_gates_input(self):
        with self.assertRaises(control.MirrorError) as off:
            control.require_agent(0)
        self.assertEqual(off.exception.code, 'not_owner')
        on = control.set_owner('agent', 'human')
        control.require_agent(on['generation'])
        with self.assertRaises(control.MirrorError) as stale:
            control.require_agent(on['generation'] - 1)
        self.assertEqual(stale.exception.code, 'stale_generation')
        off_state = control.set_owner('off', 'human')
        self.assertEqual(off_state['generation'], on['generation'] + 1)
        self.assertIsNone(off_state['enabled_by'])
        with self.assertRaises(ValueError):
            control.set_owner('human', 'human')

    def test_ownership_rechecked_between_every_line(self):
        gen = control.set_owner('agent', 'agent')['generation']
        helper = FakeHelper(on_cmd=lambda line: line == 'M 1 1' and control.set_owner('off', 'human'))
        with self.assertRaises(control.MirrorError) as err:
            control.run_batch(['M 1 1', 'M 2 2'], gen, helper)
        self.assertEqual(err.exception.code, 'stale_generation')
        self.assertEqual(helper.sent, ['M 1 1', 'C'])

    def test_bug1_helper_error_mid_batch_releases_held_input(self):
        gen = control.set_owner('agent', 'agent')['generation']
        for failure in ('ERR bad move', RuntimeError('helper exited mid-batch')):
            helper = FakeHelper(acks=['OK', failure])
            with self.assertRaises(control.MirrorError):
                control.run_batch(['B 272 1', 'M 5 5', 'B 272 0'], gen, helper)
            self.assertEqual(helper.sent, ['B 272 1', 'M 5 5', 'C'])

    def test_moves_are_offset_by_layout_origin(self):
        gen = control.set_owner('agent', 'agent')['generation']
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
        control.set_owner('agent', 'agent')
        control.set_owner('off', 'human')
        self.assertEqual(child.wait(timeout=5), -signal.SIGUSR1)
        self.assertFalse(stale.exists())

    def test_layout_box_spans_gapped_monitors(self):
        self.assertEqual(host.layout_box(LAYOUT), (0, 0, 5120, 2520))


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
        control.set_owner('agent', 'agent')
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
        self.assertEqual(json.loads(rows[2]['result']['content'][0]['text'])['enabled_by'], 'agent')
        self.assertEqual(control.read_state()['owner'], 'off')
        self.assertEqual(list(control.servers_dir().iterdir()), [])
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
