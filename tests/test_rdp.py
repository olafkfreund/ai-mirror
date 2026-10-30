"""Driving Windows through an RDP window (#92)."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api

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

    def test_type_into_other_windows_is_sent(self):
        self.send('foot', {'type': 'type', 'text': 'hi'})
        self.batch.assert_called_once()
