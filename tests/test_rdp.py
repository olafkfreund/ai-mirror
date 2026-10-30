"""Driving Windows through an RDP window (#92)."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, mcp, ocr

from test_invariants import Base, grant


class ClipboardType(Base):
    def test_write_declares_text_plain(self):
        # Text starting "d: " was sniffed as application/x-coff and could not be pasted.
        with patch.object(api.subprocess, 'run') as run:
            api.run('clipboard', {'action': 'write', 'text': 'd: x'})
        self.assertEqual(run.call_args.args[0], ['wl-copy', '--type', 'text/plain;charset=utf-8'])
        self.assertEqual(run.call_args.kwargs['input'], b'd: x')
        self.assertIs(run.call_args.kwargs['stdout'], subprocess.DEVNULL)


class RdpTyping(Base):
    def send(self, cls, action):
        gen = grant()['generation']
        rows = [{'address': '0xabc', 'class': cls}]
        with patch.object(api.host, 'windows', return_value=rows), \
                patch.object(api.control, 'run_batch', return_value={'ok': True}) as batch:
            try:
                api.run('input', {'generation': gen, 'window': '0xabc', 'actions': [action]}, by='agent')
            finally:
                self.batch = batch

    def test_type_into_rdp_is_refused_before_any_line(self):
        with self.assertRaises(api.MirrorError) as ctx:
            self.send('xfreerdp', {'type': 'type', 'text': 'hi'})
        self.assertEqual(ctx.exception.code, 'invalid')
        self.batch.assert_not_called()

    def test_key_into_rdp_is_sent(self):
        self.send('xfreerdp', {'type': 'key', 'keys': ['CTRL', 'V']})
        self.batch.assert_called_once()

    def test_type_into_versioned_freerdp_is_refused(self):
        with self.assertRaises(api.MirrorError):
            self.send('xfreerdp3', {'type': 'type', 'text': 'hi'})
        self.batch.assert_not_called()

    def test_type_into_other_windows_is_sent(self):
        self.send('foot', {'type': 'type', 'text': 'hi'})
        self.batch.assert_called_once()


# Two words on one line, one on another; coordinates are at 2x.
TSV = '\n'.join(['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext',
                 '4\t1\t1\t1\t1\t0\t20\t40\t100\t20\t-1\t',
                 '5\t1\t1\t1\t1\t1\t20\t40\t40\t20\t90.4\tOpen',
                 '5\t1\t1\t1\t1\t2\t80\t44\t40\t20\t80\tNoetad',
                 '5\t1\t1\t1\t2\t1\t20\t100\t60\t20\t95\tPaint'])


class Ocr(Base):
    def test_parse_groups_lines_halves_and_offsets(self):
        lines = ocr.parse(TSV, (1000, 500))
        self.assertEqual(lines, [{'text': 'Open Noetad', 'box': [1010, 520, 50, 12], 'conf': 85},
                                 {'text': 'Paint', 'box': [1010, 550, 30, 10], 'conf': 95}])

    def test_match_is_fuzzy_and_best_first(self):
        lines = [{'text': t} for t in ('Paint', 'Noetad', 'Open Notepad')]
        self.assertEqual([l['text'] for l in ocr.match(lines, 'Notepad')], ['Open Notepad', 'Noetad'])
        self.assertEqual([l['text'] for l in ocr.match(lines, 'paint')], ['Paint'])
        # A misread with a dropped letter, inside a longer line (#92 M2: "Noetad").
        self.assertEqual([l['text'] for l in ocr.match([{'text': 'Open Noetad now'}], 'Notepad')],
                         ['Open Noetad now'])

    def test_short_labels_are_never_guessed_and_exact_ranks_first(self):
        # "No" fuzzy-matched "Undo", and "OK" matched "Network" (#92 review).
        lines = [{'text': t} for t in ('Network', 'Undo', 'Not now', 'No', 'Open')]
        self.assertEqual([l['text'] for l in ocr.match(lines, 'No')], ['No', 'Not now'])
        self.assertEqual(ocr.match(lines, 'OK'), [])
        self.assertEqual(ocr.match(lines, 'No')[0]['score'], 1.3)

    def test_read_without_tesseract_is_unavailable(self):
        with patch.object(ocr.shutil, 'which', return_value=None):
            with self.assertRaises(api.MirrorError) as ctx:
                ocr.read([0, 0, 10, 10])
        self.assertEqual(ctx.exception.code, 'unavailable')

    def test_read_refuses_sensitive_before_any_capture(self):
        with patch.object(ocr.shutil, 'which', return_value='/bin/tesseract'), \
                patch.object(ocr.host, 'windows', return_value=[]), \
                patch.object(ocr.host, 'visible_workspaces', return_value=[]), \
                patch.object(ocr.privacy, 'refuse', return_value='nope'), \
                patch.object(ocr.subprocess, 'run') as run:
            with self.assertRaises(api.MirrorError) as ctx:
                ocr.read([0, 0, 10, 10])
        self.assertEqual(ctx.exception.code, 'sensitive')
        run.assert_not_called()

    def test_tool_is_registered_read_only_and_observing(self):
        self.assertIn('ocr', mcp.SPECS)
        self.assertIn('ocr', mcp.READ_ONLY)
        self.assertIn('ocr', api.OBSERVING)

    def test_window_becomes_its_region(self):
        row = {'address': '0xabc', 'at': [10, 20], 'size': [300, 200], 'workspace': '4'}
        with patch.object(api.host, 'windows', return_value=[row]), \
                patch.object(api.host, 'visible_workspaces', return_value={'4'}), \
                patch.object(ocr, 'read', return_value={'lines': []}) as read:
            out = api.run('ocr', {'window': '0xabc', 'find': 'x'})
        read.assert_called_once_with([10, 20, 300, 200], 'x', 50)
        self.assertIn('generation', out)

    def test_hidden_window_is_not_read(self):
        # Its rectangle would show another window's text (#92 review).
        row = {'address': '0xabc', 'at': [10, 20], 'size': [300, 200], 'workspace': '9'}
        with patch.object(api.host, 'windows', return_value=[row]), \
                patch.object(api.host, 'visible_workspaces', return_value={'4'}), \
                patch.object(ocr, 'read') as read:
            with self.assertRaises(api.MirrorError) as ctx:
                api.run('ocr', {'window': '0xabc'})
        self.assertEqual(ctx.exception.code, 'invalid')
        read.assert_not_called()

    def test_needs_exactly_one_of_window_or_region(self):
        for args in ({}, {'window': '0xabc', 'region': [0, 0, 1, 1]}, {'region': [0, 0, 0, 1]}, {'region': 'x'}):
            with self.assertRaises(ValueError):
                api.run('ocr', args)
