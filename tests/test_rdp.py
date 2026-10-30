"""Driving Windows through an RDP window (#92)."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api

from test_invariants import Base


class ClipboardType(Base):
    def test_write_declares_text_plain(self):
        # Text starting "d: " was sniffed as application/x-coff and could not be pasted.
        with patch.object(api.subprocess, 'run') as run:
            api.run('clipboard', {'action': 'write', 'text': 'd: x'})
        self.assertEqual(run.call_args.args[0], ['wl-copy', '--type', 'text/plain;charset=utf-8'])
        self.assertEqual(run.call_args.kwargs['input'], b'd: x')
        self.assertIs(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
