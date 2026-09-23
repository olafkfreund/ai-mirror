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


class Content(unittest.TestCase):
    """#33: content: true must mean there is something to find or act on."""

    def test_anonymous_groupings_are_not_content(self):
        from ai_mirror import a11y
        row = {'id': '11.0.0.0.0', 'role': 'grouping', 'name': '', 'states': ['sensitive']}
        self.assertFalse(a11y._actionable(row, 5))

    def test_a_named_node_is_content(self):
        from ai_mirror import a11y
        self.assertTrue(a11y._actionable({'role': 'push button', 'name': 'Place order'}, 3))

    def test_an_actionable_unnamed_node_is_content(self):
        from ai_mirror import a11y
        self.assertTrue(a11y._actionable({'role': 'entry', 'name': '', 'actions': ['activate']}, 4))

    def test_a_shallow_named_node_is_not_content(self):
        # An application or its frame is not content, however well named.
        from ai_mirror import a11y
        self.assertFalse(a11y._actionable({'role': 'frame', 'name': 'Text Editor'}, 1))

    def test_the_note_distinguishes_empty_from_unusable(self):
        from ai_mirror import a11y
        nothing = a11y._coverage(visited=2, deep=False, truncated=False, actionable=False)
        hollow = a11y._coverage(visited=24, deep=True, truncated=False, actionable=False)
        self.assertIn('no controls under them', nothing['note'])
        self.assertIn('no named or actionable nodes', hollow['note'])
        self.assertFalse(hollow['content'])


class Attribution(Base):
    """#34: the person deciding is told who wants their desktop."""

    def test_the_cli_asks_as_an_agent(self):
        import io, json, contextlib
        from ai_mirror import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(['control', 'agent'])
        self.assertEqual(json.loads(out.getvalue())['request']['by'], 'agent')

    def test_turning_control_off_is_still_the_human(self):
        # Super+Shift+Escape runs this, and it is the person pressing it.
        import io, contextlib
        from unittest.mock import patch
        from ai_mirror import cli
        seen = {}
        with patch.object(cli.api, 'run', side_effect=lambda op, args, by='human': seen.update(by=by) or {}), \
             contextlib.redirect_stdout(io.StringIO()):
            cli.main(['control', 'off'])
        self.assertEqual(seen['by'], 'human')


class RegionForms(unittest.TestCase):
    """#35: the CLI accepts the form the MCP tool description hands an agent."""

    def test_both_forms_parse_the_same(self):
        from ai_mirror.cli import region
        self.assertEqual(region('967,38,922,700'), [967, 38, 922, 700])
        self.assertEqual(region('[967,38,922,700]'), [967, 38, 922, 700])
        self.assertEqual(region('[967, 38, 922, 700]'), [967, 38, 922, 700])

    def test_the_error_names_the_expected_form(self):
        import argparse
        from ai_mirror.cli import region
        with self.assertRaises(argparse.ArgumentTypeError) as caught:
            region('967,38,922')
        self.assertIn('x,y,width,height', str(caught.exception))


class SetText(unittest.TestCase):
    """#36: two causes, two messages -- one of them tells the caller what does work."""

    class FakeAccessible:
        def __init__(self, editable):
            self._editable = editable

        def get_editable_text_iface(self):
            return self._editable

        def get_role_name(self):
            return 'entry'

        def get_name(self):
            return 'Customer'

    def _act(self, accessible, text):
        from unittest.mock import patch
        from ai_mirror import a11y
        from ai_mirror.control import MirrorError
        with patch.object(a11y, 'resolve', return_value=(accessible, None)):
            with self.assertRaises(MirrorError) as caught:
                a11y.act('11.0.0', 'set_text', text)
        return caught.exception

    def test_missing_text_says_so(self):
        error = self._act(self.FakeAccessible(editable=object()), None)
        self.assertEqual(str(error), 'unsupported: set_text needs text')

    def test_a_missing_interface_names_the_path_that_works(self):
        error = self._act(self.FakeAccessible(editable=None), 'Ada Lovelace')
        self.assertIn('EditableText', str(error))
        self.assertIn('focus', str(error))
        self.assertIn('input', str(error))


class Departed(unittest.TestCase):
    """#39: what left the baseline, so a returning surface reads differently from a new one."""

    def test_names_are_added_once(self):
        from ai_mirror.control import _forget_departed
        first = _forget_departed([], {'notification'})
        self.assertEqual(first, ['notification'])
        self.assertEqual(_forget_departed(first, {'notification'}), ['notification'])

    def test_the_list_is_capped(self):
        from ai_mirror.control import _forget_departed, DEPARTED_CAP
        departed = []
        for i in range(DEPARTED_CAP + 10):
            departed = _forget_departed(departed, {f'surface-{i:03d}'})
        self.assertEqual(len(departed), DEPARTED_CAP)
        # the oldest go first, so the most recent are what a message can name
        self.assertIn(f'surface-{DEPARTED_CAP + 9:03d}', departed)
        self.assertNotIn('surface-000', departed)


class ContinuousPresence(Base):
    """#39: exempt while mapped continuously since the grant, not merely present at it."""

    def _grant_with(self, namespaces):
        from unittest.mock import patch
        from ai_mirror import control
        layers = [{'address': f'0x{i}', 'namespace': ns, 'level': 2 if ns != 'omarchy-background' else 0,
                   'monitor': 'eDP-1'} for i, ns in enumerate(namespaces)]
        with patch.object(control.host, 'layers', return_value=layers):
            return grant()['generation']

    def _check_with(self, namespaces, generation):
        """Run the guard as a window-addressed line would, with these layers mapped."""
        from unittest.mock import patch
        from ai_mirror import control
        layers = [{'address': f'0x{i}', 'namespace': ns, 'level': 2 if ns != 'omarchy-background' else 0,
                   'monitor': 'eDP-1'} for i, ns in enumerate(namespaces)]
        helper = FakeHelper()
        with patch.object(control.host, 'layers', return_value=layers), \
             patch.object(control.host, 'focused_address', return_value='WINDOW'):
            try:
                control.run_batch(['T hi'], generation, helper, window='WINDOW')
                return None
            except control.MirrorError as error:
                return error

    def test_a_surface_that_goes_leaves_the_baseline(self):
        from ai_mirror import control
        generation = self._grant_with(['omarchy-background', 'omarchy-bar', 'omarchy-ai-mirror-confirm'])
        self.assertIn('omarchy-ai-mirror-confirm', control.read_state()['baseline_layers'])
        self.assertIsNone(self._check_with(['omarchy-background', 'omarchy-bar'], generation))
        state = control.read_state()
        self.assertEqual(state['baseline_layers'], ['omarchy-background', 'omarchy-bar'])
        self.assertEqual(state['baseline_departed'], ['omarchy-ai-mirror-confirm'])

    def test_a_level_zero_surface_is_not_dropped(self):
        from ai_mirror import control
        generation = self._grant_with(['omarchy-background', 'omarchy-bar'])
        self.assertIsNone(self._check_with(['omarchy-background', 'omarchy-bar'], generation))
        self.assertEqual(control.read_state()['baseline_layers'],
                         ['omarchy-background', 'omarchy-bar'])

    def test_an_unchanged_baseline_is_not_rewritten(self):
        from unittest.mock import patch
        from ai_mirror import control
        generation = self._grant_with(['omarchy-background', 'omarchy-bar'])
        with patch.object(control, '_write', side_effect=AssertionError('wrote with nothing to change')):
            self.assertIsNone(self._check_with(['omarchy-background', 'omarchy-bar'], generation))

    def test_a_surface_that_went_and_came_back_is_refused(self):
        generation = self._grant_with(['omarchy-background', 'omarchy-bar', 'notification'])
        self.assertIsNone(self._check_with(['omarchy-background', 'omarchy-bar'], generation))
        error = self._check_with(['omarchy-background', 'omarchy-bar', 'notification'], generation)
        self.assertIsNotNone(error)
        self.assertEqual(error.code, 'wrong_target')
        self.assertIn('notification', str(error))

    def test_the_two_shapes_read_differently(self):
        generation = self._grant_with(['omarchy-background', 'omarchy-bar', 'notification'])
        self._check_with(['omarchy-background', 'omarchy-bar'], generation)
        came_back = self._check_with(['omarchy-background', 'omarchy-bar', 'notification'], generation)
        self.assertIn('went away and came back', str(came_back))
        brand_new = self._check_with(['omarchy-background', 'omarchy-bar', 'nixi'], generation)
        self.assertIn('opened since control was granted', str(brand_new))
        self.assertNotIn('went away and came back', str(brand_new))
