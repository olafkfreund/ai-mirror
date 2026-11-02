"""`screenshot window=<address>` (#100): one window, even on a hidden workspace.

No desktop: windows, monitors and grim are stubbed; the fake grim writes a PNG
header of the size it was asked for.
"""
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import cli, control, host, mcp

from test_invariants import Base


def win(address, workspace='1', at=(100, 50), size=(800, 600), stable='18000005', **extra):
    row = {'address': address, 'class': 'foot', 'title': 'shell', 'at': list(at), 'size': list(size),
           'monitor': 1, 'workspace': workspace}
    if stable is not None:
        row['stableId'] = stable
    return {**row, **extra}


class WindowCapture(Base):
    def capture(self, windows, window='0xa', visible=('1',), **kwargs):
        self.calls = []

        def grim(argv, **kw):
            self.calls.append((argv, kw))
            w, h = 800, 600
            Path(argv[-1]).write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', w, h))
            return SimpleNamespace(returncode=0, stderr='')

        with patch.object(host, 'windows', return_value=windows), \
             patch.object(host, 'visible_workspaces', return_value=set(visible)), \
             patch.object(host, 'monitors', return_value=[{'id': 1, 'name': 'DP-1'}]), \
             patch.object(control.subprocess, 'run', grim):
            return control.screenshot(control.root() / 'w.png', window=window, **kwargs)

    def test_argv_region_and_monitor_name(self):
        got = self.capture([win('0xa')])
        argv, kw = self.calls[0]
        self.assertEqual(argv[:3], ['grim', '-T', '18000005'])
        self.assertIs(kw['stdin'], control.subprocess.DEVNULL)
        self.assertEqual(got['region'], [100, 50, 800, 600])
        self.assertEqual(got['output'], 'DP-1')
        self.assertEqual((got['window'], got['visible'], got['view_only']), ('0xa', True, False))

    def test_bad_window_runs_no_grim(self):
        for windows, addr in (([win('0xa')], '0xzz'), ([win('0xa', stable=None)], '0xa'),
                              ([win('0xa', stable='1; rm')], '0xa')):
            with self.subTest(addr=addr, windows=windows):
                with self.assertRaises(control.MirrorError) as ctx:
                    self.capture(windows, window=addr)
                self.assertEqual(ctx.exception.code, 'invalid')
                self.assertEqual(self.calls, [])

    def test_private_window_refused_visible_or_hidden(self):
        for ws in ('1', '9'):
            with self.subTest(workspace=ws):
                with self.assertRaises(control.MirrorError) as ctx:
                    self.capture([win('0xa', workspace=ws, **{'class': '1Password'})])
                self.assertEqual(ctx.exception.code, 'sensitive')
                self.assertEqual(self.calls, [])

    def test_hidden_workspace_is_view_only(self):
        got = self.capture([win('0xa', workspace='9')])
        self.assertTrue(got['view_only'])
        self.assertFalse(got['visible'])

    def test_overlapped_is_view_only_with_note(self):
        got = self.capture([win('0xa'), win('0xb', at=(200, 100), size=(50, 50))])
        self.assertTrue(got['view_only'])
        self.assertIn('overlaps', got['note'])

    def test_window_excludes_output_and_region(self):
        for kw in ({'output': 'DP-1'}, {'region': [0, 0, 10, 10]}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.capture([win('0xa')], **kw)

    def test_from_frame_refuses_view_only(self):
        frame = {'generation': 1, 'region': [0, 0, 800, 600], 'width': 800, 'height': 600,
                 'window': '0xa', 'view_only': True}
        with patch.dict(mcp.FRAMES, {'f': frame}, clear=True):
            with self.assertRaises(control.MirrorError) as ctx:
                mcp.from_frame({'frame': 'f', 'actions': [{'type': 'click', 'x': 1, 'y': 1}]})
        self.assertEqual(ctx.exception.code, 'invalid')

    def test_cli_parses_window(self):
        args = cli.build_parser().parse_args(['screenshot', '--window', '0xa'])
        self.assertEqual(args.window, '0xa')


if __name__ == '__main__':
    unittest.main()
