"""The audit line says what answered a control request (#57).

Evidence, not proof: every field is reported by the answering process itself.
Needs no desktop; Base arms the guard and isolates XDG_RUNTIME_DIR.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, control

from test_invariants import Base


class Answerer(Base):
    def ask(self):
        control.set_owner('agent', 'agent')
        return control.read_state()['request']['id']

    def answer(self, mode, **args):
        return api.run('control', {'mode': mode, **args}, by='human')

    def last(self):
        return control.read_audit(0)['entries'][-1]

    def test_cli_confirm_records_the_path(self):
        self.answer('confirm', id=self.ask())
        got = self.last()
        self.assertEqual((got['event'], got['via'], got['id_given']), ('confirmed', 'cli', True))
        self.assertIsInstance(got['pid'], int)
        self.assertIsInstance(got.get('chain'), (str, type(None)))

    def test_dialog_key_is_recorded(self):
        self.answer('confirm', id=self.ask(), via='dialog-key', key=65, mods=0)
        got = self.last()
        self.assertEqual((got['via'], got['key'], got['mods']), ('dialog-key', 65, 0))

    def test_bad_via_is_refused(self):
        rid = self.ask()
        for args in ({'via': 'cli'}, {'via': 'bogus'}, {'via': 'dialog-click', 'key': 65},
                     {'via': 'dialog-key', 'key': -1}, {'via': 'dialog-key', 'key': True}):
            with self.assertRaises(ValueError):
                self.answer('confirm', id=rid, **args)
        self.assertEqual(control.read_state()['owner'], 'pending')

    def test_confirm_needs_an_id(self):
        self.ask()
        with self.assertRaises(control.MirrorError) as got:
            self.answer('confirm')
        self.assertEqual(got.exception.code, 'invalid')
        self.assertEqual(control.read_state()['owner'], 'pending')

    def test_deny_without_an_id_works(self):
        self.ask()
        self.answer('deny')
        got = self.last()
        self.assertEqual((got['event'], got['id_given']), ('denied', False))

    def test_unreadable_proc_does_not_block_the_answer(self):
        rid = self.ask()
        real = open

        def proc_fails(path, *a, **k):
            if str(path).startswith('/proc/'):
                raise OSError
            return real(path, *a, **k)
        with patch('builtins.open', proc_fails):
            self.answer('confirm', id=rid)
        self.assertEqual(control.read_state()['owner'], 'agent')
        self.assertIsNone(self.last().get('chain'))

    def test_old_entries_still_render(self):
        old = {'event': 'confirmed', 'at': '2026-09-27T06:00:00+0100', 'request': 'x', 'by': 'agent'}
        cli.render_audit({'entries': [old], 'source': 'present', 'total': 1, 'skipped': 0})


if __name__ == '__main__':
    unittest.main()
