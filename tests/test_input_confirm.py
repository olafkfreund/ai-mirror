"""#101: `input` confirm -- did the state CHANGE after the keystroke."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, control, wait

from test_invariants import Base

CLICK = [{'type': 'click', 'x': 1, 'y': 1}]


def layers(*names):
    return {'DP-1': {'levels': {'0': [{'namespace': n} for n in names]}}}


class Confirm(Base):
    def setUp(self):
        super().setUp()
        self.world = {'layers': layers(), 'activewindow': {'address': '0x1'},
                      'clients': [{'address': '0x1', 'title': 'old'}]}
        self.after = {}      # state changes the "batch" makes
        self.sent = 0
        self.asked = []      # queries made after the batch was sent
        for target, stub in ((wait, ('_ask', self.ask)),
                             (control, ('require_agent', lambda g: None)),
                             (control, ('run_batch', self.run_batch))):
            p = patch.object(target, stub[0], stub[1])
            p.start()
            self.addCleanup(p.stop)

    def ask(self, request, budget):
        if self.sent:
            self.asked.append(request)
        value = self.world[request]
        if isinstance(value, Exception):
            raise value
        return value

    def run_batch(self, lines, generation, **kw):
        self.sent += 1
        self.world.update(self.after)
        if isinstance(self.after.get('boom'), Exception):
            raise self.after['boom']
        return {'ok': True}

    def go(self, confirm=None, **kw):
        args = {'generation': 1, 'actions': CLICK, **kw}
        if confirm is not None:
            args['confirm'] = confirm
        return api.run('input', args)

    def test_a_layer_that_appears_is_confirmed(self):
        self.after = {'layers': layers('panel')}
        out = self.go({'layer': 'panel', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'confirmed')
        self.assertEqual(out['confirm']['predicate'], 'layer')
        self.assertTrue(out['ok'])

    def test_a_layer_already_there_is_not_evidence_and_is_not_polled(self):
        self.world['layers'] = layers('panel')
        out = self.go({'layer': 'panel', 'timeout': 0.1})
        self.assertEqual(out['confirm'], {'result': 'not_confirmed', 'polls': 0, 'predicate': 'layer',
                                          'waited_ms': 0, 'held_before': True})
        self.assertEqual(self.sent, 1)
        self.assertEqual(self.asked, [])

    def test_a_layer_that_never_appears_is_not_confirmed(self):
        out = self.go({'layer': 'panel', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'not_confirmed')
        self.assertNotIn('held_before', out['confirm'])

    def test_absent_closing_is_confirmed(self):
        self.world['layers'] = layers('panel')
        self.after = {'layers': layers()}
        out = self.go({'layer': 'panel', 'absent': True, 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'confirmed')

    def test_focus_changed(self):
        self.after = {'activewindow': {'address': '0x2'}}
        self.assertEqual(self.go({'focus_changed': True, 'timeout': 0.1})['confirm']['result'], 'confirmed')

    def test_focus_unchanged(self):
        out = self.go({'focus_changed': True, 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'not_confirmed')

    def test_title_changed(self):
        self.after = {'clients': [{'address': '0x1', 'title': 'new'}]}
        out = self.go({'title_changed': '0x1', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'confirmed')

    def test_title_window_gone(self):
        self.after = {'clients': []}
        out = self.go({'title_changed': '0x1', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'confirmed')

    def test_title_of_an_unknown_window_is_unavailable_and_still_sent(self):
        out = self.go({'title_changed': '0x9', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'unavailable')
        self.assertIn('0x9', out['confirm']['reason'])
        self.assertEqual(self.sent, 1)

    def test_an_unreadable_before_state_is_unavailable_and_still_sent(self):
        self.world['layers'] = RuntimeError('no compositor')
        out = self.go({'layer': 'panel', 'timeout': 0.1})
        self.assertEqual(out['confirm']['result'], 'unavailable')
        self.assertIn('no compositor', out['confirm']['reason'])
        self.assertEqual(self.sent, 1)
        self.assertEqual(self.asked, [])

    def test_a_failing_batch_raises_and_nothing_is_polled(self):
        self.after = {'boom': RuntimeError('helper died')}
        with self.assertRaises(RuntimeError):
            self.go({'layer': 'panel', 'timeout': 0.1})
        self.assertEqual(self.asked, [])

    def test_invalid_confirm_sends_nothing(self):
        for bad in ({}, {'layer': 'a', 'focus_changed': True}, {'focus_changed': False},
                    {'focus_changed': True, 'absent': True}, {'layer': 'a', 'timeout': -1},
                    {'layer': 'a', 'timeout': float('nan')}, 'layer'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.go(bad)
        self.assertEqual(self.sent, 0)

    def test_no_confirm_no_key(self):
        self.assertNotIn('confirm', self.go())
        self.assertEqual(self.asked, [])

    def test_cli_accepts_confirm(self):
        ns = cli.build_parser().parse_args(['input', '--generation', '1', '--confirm', '{"layer":"x"}', '[]'])
        self.assertEqual(ns.confirm, {'layer': 'x'})


if __name__ == '__main__':
    unittest.main()
