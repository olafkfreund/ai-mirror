"""#30: a result a caller cannot check must not be wrong in the reassuring direction."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror.control import MirrorError

from test_invariants import Base, FakeHelper, grant


class Details(unittest.TestCase):
    """MirrorError carries the facts its message states in prose."""

    def test_details_are_kept(self):
        error = MirrorError('wrong_target', 'partial', {'delivered': 9, 'of': 14})
        self.assertEqual(error.details, {'delivered': 9, 'of': 14})

    def test_two_argument_calls_still_work(self):
        error = MirrorError('unavailable', 'no helper')
        self.assertEqual(error.details, {})
        self.assertEqual(str(error), 'unavailable: no helper')


if __name__ == '__main__':
    unittest.main()


class Surfaces(unittest.TestCase):
    """Both surfaces hand the details on; neither hides them in the sentence."""

    def test_cli_renders_details(self):
        import io, json, contextlib
        from unittest.mock import patch
        from ai_mirror import cli
        boom = MirrorError('wrong_target', 'partial: 9 of 14', {'delivered': 9, 'of': 14})
        out = io.StringIO()
        with patch.object(cli.api, 'run', side_effect=boom), contextlib.redirect_stdout(out):
            cli.main(['status'])
        error = json.loads(out.getvalue())['error']
        self.assertEqual(error['code'], 'wrong_target')
        self.assertEqual((error['delivered'], error['of']), (9, 14))

    def test_mcp_renders_details(self):
        import json
        from unittest.mock import patch
        from ai_mirror import mcp
        boom = MirrorError('wrong_target', 'partial: 9 of 14', {'delivered': 9, 'of': 14})
        with patch.object(mcp.api, 'run', side_effect=boom):
            result = mcp.call_tool('status', {})
        self.assertTrue(result['isError'])
        payload = json.loads(result['content'][0]['text'])
        self.assertEqual((payload['delivered'], payload['of']), (9, 14))


class LineOwners(unittest.TestCase):
    """encode can say which action emitted each line, so a partial delivery counts in actions."""

    def test_every_line_has_an_owner_in_order(self):
        from ai_mirror.input import encode
        actions = [{'type': 'type', 'text': 'hi'},
                   {'type': 'key', 'keys': ['CTRL', 'A']},
                   {'type': 'click', 'x': 1, 'y': 2, 'modifiers': ['SHIFT']}]
        lines, owners = encode(actions, with_owners=True)
        self.assertEqual(len(lines), len(owners))
        self.assertEqual(owners, sorted(owners))
        self.assertEqual(set(owners), {0, 1, 2})
        # the modifier's press and release both belong to the action that asked for it
        self.assertEqual(owners[-1], 2)

    def test_default_call_is_unchanged(self):
        from ai_mirror.input import encode
        self.assertIsInstance(encode([{'type': 'click', 'x': 1, 'y': 2}]), list)


class PartialDelivery(Base):
    """#30: a refusal partway through a batch must not claim nothing was sent."""

    def _run(self, fail_before_line):
        """Deliver a batch whose focus check starts refusing before line N."""
        from unittest.mock import patch
        from ai_mirror import control
        from ai_mirror.input import encode
        generation = grant()['generation']
        lines, owners = encode([{'type': 'type', 'text': 'AB'},
                                {'type': 'key', 'keys': ['Return']},
                                {'type': 'key', 'keys': ['CTRL', 'd']}], with_owners=True)
        helper = FakeHelper()
        calls = {'n': 0}

        def focus():
            calls['n'] += 1
            return 'WINDOW' if calls['n'] <= fail_before_line else 'OTHER'

        with patch.object(control.host, 'focused_address', side_effect=focus), \
             patch.object(control.host, 'layers', return_value=[]):
            with self.assertRaises(control.MirrorError) as caught:
                control.run_batch(lines, generation, helper, window='WINDOW', owners=owners)
        return caught.exception, lines, helper

    def test_nothing_delivered_keeps_the_old_wording(self):
        error, lines, helper = self._run(fail_before_line=0)
        self.assertIn('input was NOT sent', str(error))
        self.assertEqual(error.details, {})
        self.assertEqual([line for line in helper.sent if line != 'C'], [])

    def test_a_delivered_prefix_is_reported(self):
        error, lines, helper = self._run(fail_before_line=3)
        sent = [line for line in helper.sent if line != 'C']
        self.assertEqual(len(sent), 3)
        self.assertNotIn('input was NOT sent', str(error))
        self.assertIn('partial: 3 of %d lines delivered' % len(lines), str(error))
        self.assertEqual(error.details['delivered'], 3)
        self.assertEqual(error.details['of'], len(lines))

    def test_the_count_is_in_actions_too(self):
        error, lines, _ = self._run(fail_before_line=3)
        self.assertEqual(error.details['actions_total'], 3)
        self.assertLessEqual(error.details['actions_completed'], 3)
        self.assertIn('actions', str(error))


class Codes(Base):
    """#31: "you aimed at the wrong thing" and "you lost control" are different answers."""

    def test_a_focus_mismatch_is_wrong_target(self):
        from unittest.mock import patch
        from ai_mirror import control
        with patch.object(control.host, 'focused_address', return_value='OTHER'), \
             patch.object(control.host, 'layers', return_value=[]):
            with self.assertRaises(control.MirrorError) as caught:
                control._require_target('WINDOW')
        self.assertEqual(caught.exception.code, 'wrong_target')

    def test_a_moved_generation_is_still_stale_generation(self):
        from ai_mirror import control
        granted = grant()
        with self.assertRaises(control.MirrorError) as caught:
            control.require_agent(granted['generation'] + 1)
        self.assertEqual(caught.exception.code, 'stale_generation')


class Baseline(Base):
    """#29: surfaces mapped since the grant are in the way; the furniture is not."""

    def _type_with(self, at_grant, now_mapped):
        from unittest.mock import patch
        from ai_mirror import control
        with patch.object(control.host, 'layers', return_value=at_grant):
            generation = grant()['generation']
        helper = FakeHelper()
        with patch.object(control.host, 'layers', return_value=now_mapped), \
             patch.object(control.host, 'focused_address', return_value='WINDOW'):
            return helper, control.run_batch(['T hi'], generation, helper, window='WINDOW')

    def test_an_unreadable_baseline_does_not_refuse_everything(self):
        # "We could not look" must not become "everything is suspicious", which
        # would refuse all typing for the life of the grant.
        from unittest.mock import patch
        from ai_mirror import control
        with patch.object(control.host, 'layers', side_effect=RuntimeError('no compositor')):
            generation = grant()['generation']
        self.assertNotIn('baseline_layers', control.read_state())
        helper = FakeHelper()
        with patch.object(control.host, 'layers', return_value=[{'address': '0x1', 'namespace': 'panel',
                                                                'level': 3, 'monitor': 'eDP-1'}]), \
             patch.object(control.host, 'focused_address', return_value='WINDOW'):
            control.run_batch(['T hi'], generation, helper, window='WINDOW')
        self.assertEqual(helper.sent, ['T hi'])

    def test_a_surface_below_the_keyboard_levels_is_not_in_the_way(self):
        bar = {'address': '0xbar', 'namespace': 'omarchy-bar', 'level': 2, 'monitor': 'eDP-1'}
        wallpaper = {'address': '0xwall', 'namespace': 'new-wallpaper', 'level': 0, 'monitor': 'eDP-1'}
        helper, _ = self._type_with([bar], [bar, wallpaper])
        self.assertEqual(helper.sent, ['T hi'])


class Doctor(Base):
    """#32: the check that exists for "nothing works" must not pass when nothing works."""

    def test_an_unreachable_compositor_fails(self):
        import os
        from unittest.mock import patch
        from ai_mirror import api
        with patch.object(api.host, 'focused_address',
                          side_effect=RuntimeError('Hyprland: HYPRLAND_INSTANCE_SIGNATURE not set!')), \
             patch.dict(os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': '', 'WAYLAND_DISPLAY': ''}):
            report = api.doctor()
        self.assertFalse(report['ok'])
        self.assertIn('HYPRLAND_INSTANCE_SIGNATURE', ' '.join(report['unset']))
        self.assertIn('no desktop session', report['hint'])

    def test_a_reachable_compositor_passes(self):
        from unittest.mock import patch
        from ai_mirror import api
        with patch.object(api.host, 'focused_address', return_value=None), \
             patch.object(api.shutil, 'which', return_value='/bin/true'), \
             patch.object(api.control, 'helper_binary', return_value='/bin/true'):
            report = api.doctor()
        self.assertTrue(report['ok'])
        self.assertEqual(report['compositor'], 'reachable')
