"""Change-aware capture through MCP, with no compositor or desktop input."""
import json
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import control, guard, host, mcp
from test_invariants import Base
from test_window_capture import win

ME = {'pid': 1, 'start': 2}


def png(width=800, height=600, pixel=b'\xff'):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    header = struct.pack('>2I5B', width, height, 8, 0, 0, 0, 0)
    rows = (b'\x00' + pixel * width) * height
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


class Comparison(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, mcp, 'COMPARISON', None)
        mcp.COMPARISON = None
        self.state = {'owner': 'agent', 'held_by': ME, 'generation': 1, 'last_input': control.now()}
        self.rows = [win('0xa')]
        self.png = png()
        for obj, name, value in ((control, 'SERVER', ME), (control, 'read_state', lambda: self.state),
                                 (host, 'windows', lambda: self.rows),
                                 (host, 'monitors', lambda: [{'id': 1, 'name': 'DP-1'}]),
                                 (host, 'visible_workspaces', lambda: {'1'}),
                                 (control, '_read_png', lambda process: self.png),
                                 (control, '_grim_stdout', lambda *args: None)):
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(mcp.FRAMES, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def capture(self, **extra):
        result = mcp.call_tool('screenshot', {'compare': True, 'window': '0xa', 'generation': 1, **extra})
        return result, json.loads(result['content'][0]['text'])

    def test_baseline_unchanged_changed_and_same_image(self):
        first, a = self.capture()
        second, b = self.capture()
        self.png = png(pixel=b'\x00')
        third, c = self.capture()
        self.assertEqual([x['comparison']['status'] for x in (a, b, c)],
                         ['baseline', 'unchanged', 'changed'])
        self.assertEqual(b['comparison']['previous_frame'], a['frame'])
        self.assertEqual(c['comparison']['previous_frame'], b['frame'])
        self.assertEqual(first['content'][1]['data'], second['content'][1]['data'])
        self.assertNotEqual(second['content'][1]['data'], third['content'][1]['data'])
        self.assertEqual(mcp.FRAMES[c['frame']]['region'], c['region'])

    def test_identity_and_visibility_changes_rebaseline(self):
        self.capture()
        for row in (win('0xa', stable='18000006'), win('0xa', at=(101, 50)),
                    win('0xa', size=(1000, 600)), win('0xa', workspace='9'),
                    win('0xa')):
            self.rows[:] = [row]
            _, got = self.capture()
            self.assertEqual(got['comparison']['status'], 'baseline')
        self.rows[:] = [win('0xa'), win('0xb', at=(200, 100), size=(50, 50))]
        _, covered = self.capture()
        self.assertTrue(covered['view_only'])
        self.assertEqual(covered['comparison']['status'], 'baseline')
        refused = mcp.call_tool('input', {'frame': covered['frame'], 'actions': [{'type': 'click', 'x': 1, 'y': 1}]})
        self.assertTrue(refused['isError'])
        self.assertEqual(json.loads(refused['content'][0]['text'])['code'], 'invalid')
        self.png = png(640, 480)
        self.assertEqual(self.capture(max_size=640)[1]['comparison']['status'], 'baseline')

    def test_changed_during_capture_or_private_after_is_not_published(self):
        initial = len(mcp.FRAMES)
        def change(_):
            self.rows[:] = [win('0xa', at=(102, 50))]
            return self.png
        with patch.object(control, '_read_png', change):
            result, _ = self.capture()
        self.assertTrue(result['isError'])
        self.assertEqual(len(mcp.FRAMES), initial)
        self.rows[:] = [win('0xa')]
        def private(_):
            self.rows[:] = [win('0xa', **{'class': '1Password'})]
            return self.png
        with patch.object(control, '_read_png', private):
            result, error = self.capture()
        self.assertEqual(error['code'], 'sensitive')
        self.assertEqual(len(mcp.FRAMES), initial)

    def test_private_before_and_invalid_image(self):
        self.rows[:] = [win('0xa', **{'class': '1Password'})]
        self.assertEqual(self.capture()[1]['code'], 'sensitive')
        self.rows[:] = [win('0xa')]
        for bad in (b'wrong', png()[:32], png(1281, 1)):
            self.png = bad
            result, error = self.capture()
            self.assertTrue(result['isError'])
            self.assertEqual(error['code'], 'unavailable')
        self.assertEqual(mcp.FRAMES, {})

    def test_grant_failures_clear_baseline_and_refuse(self):
        self.capture()
        for changes, code in (({'owner': 'off'}, 'not_owner'),
                              ({'held_by': {'pid': 9}}, 'not_owner'),
                              ({'held_by': None}, 'not_owner'),
                              ({'generation': 2}, 'stale_generation'),
                              ({'last_input': control.now() - control.IDLE_LIMIT - 1}, 'not_owner')):
            self.state.update({'owner': 'agent', 'held_by': ME, 'generation': 1,
                               'last_input': control.now()})
            self.capture()
            self.state.update(changes)
            self.assertEqual(self.capture()[1]['code'], code)
            self.assertIsNone(mcp.COMPARISON)
        self.state.update({'owner': 'agent', 'held_by': ME, 'generation': 2,
                           'last_input': control.now()})
        result = mcp.call_tool('screenshot', {'compare': True, 'window': '0xa', 'generation': 2})
        self.assertEqual(json.loads(result['content'][0]['text'])['comparison']['status'], 'baseline')

    def test_revocation_during_capture_and_validation(self):
        self.capture()
        def revoke(_):
            self.state['owner'] = 'off'
            return self.png
        with patch.object(control, '_read_png', revoke):
            result, _ = self.capture()
        self.assertTrue(result['isError'])
        self.assertIsNone(mcp.COMPARISON)
        self.state['owner'] = 'agent'
        self.assertEqual(self.capture()[1]['comparison']['status'], 'baseline')
        for args in ({'image': False}, {'output': 'all'}, {'region': [0, 0, 1, 1]},
                     {'max_size': 1281}, {'window': ''}, {'generation': True}):
            self.assertTrue(self.capture(**args)[0]['isError'])

    def test_ordinary_capture_does_not_replace_baseline(self):
        _, a = self.capture()
        with patch.object(mcp.api, 'run', return_value={
            'path': str(control.root() / 'none.png'), 'generation': 1, 'owner': 'agent',
            'width': 800, 'height': 600, 'region': [100, 50, 800, 600], 'output': 'DP-1'}):
            self.assertFalse(mcp.call_tool('screenshot', {'image': False})['isError'])
        _, b = self.capture()
        self.assertEqual(b['comparison']['previous_frame'], a['frame'])

    def test_revocation_during_encoding_discards_image(self):
        _, first = self.capture()
        encode = mcp.base64.b64encode

        def revoke(image):
            self.state['owner'] = 'off'
            return encode(image)

        with patch.object(mcp.base64, 'b64encode', revoke):
            result, error = self.capture()
        self.assertTrue(result['isError'])
        self.assertEqual(error['code'], 'not_owner')
        self.assertEqual(len(result['content']), 1)
        self.assertEqual(list(mcp.FRAMES), [first['frame']])
        self.assertIsNone(mcp.COMPARISON)

    def test_release_clears_baseline_and_aborts_helper(self):
        self.capture()
        with patch.object(control.HELPER, 'abort') as abort:
            mcp.release()
        self.assertIsNone(mcp.COMPARISON)
        abort.assert_called_once_with()


class Reader(Base):
    def process(self, script):
        return subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_success_failure_and_size_limit(self):
        self.assertEqual(control._read_png(self.process("import sys;sys.stdout.buffer.write(b'ok')")), b'ok')
        with self.assertRaises(control.MirrorError):
            control._read_png(self.process('raise SystemExit(3)'))
        p = self.process("import sys;sys.stdout.buffer.write(b'x' * (8*1024*1024+1))")
        with self.assertRaises(control.MirrorError):
            control._read_png(p)
        self.assertIsNotNone(p.poll())
        self.assertTrue(p.stdout.closed)

    def test_timeout_kills_and_reaps(self):
        p = self.process('import time;time.sleep(10)')
        with patch.object(control.time, 'monotonic', side_effect=[0, 0.01]):
            # Force a short select timeout without waiting five seconds.
            with patch.object(control.select, 'select', return_value=([], [], [])):
                with self.assertRaises(control.MirrorError):
                    control._read_png(p)
        self.assertIsNotNone(p.poll())
        self.assertTrue(p.stdout.closed)

    def test_spawn_guard(self):
        with self.assertRaises(guard.Blocked):
            control._grim_stdout('18000005', 1.0)
