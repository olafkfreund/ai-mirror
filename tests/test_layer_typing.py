"""#26: typing into a layer surface -- a menu, panel or launcher -- and from the CLI."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, control, host
from ai_mirror.control import MirrorError

from test_invariants import Base, FakeHelper, grant

WINDOW = '0x5d811eac1ea0'
PANEL = '0x5efa92d0b780'
BAR = '0x5efa905c4d10'
TOAST = '0x5efa93000000'

# What razer's Hyprland 0.56 printed with nixarchy-pkg's panel open.
RAZER_LAYERS = {'eDP-1': {'levels': {
    '0': [{'address': '0x5efa8e8b6a50', 'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'alpha': 1,
           'namespace': 'omarchy-background', 'pid': 1}],
    '1': [],
    '2': [{'address': BAR, 'x': 0, 'y': 0, 'w': 1920, 'h': 26, 'alpha': 1,
           'namespace': 'omarchy-bar', 'pid': 1}],
    '3': [{'address': PANEL, 'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'alpha': 1,
           'namespace': 'nixarchy-pkg-menu', 'pid': 2}],
}}}


def layer(address, namespace, level, monitor='eDP-1'):
    return {'address': address, 'namespace': namespace, 'monitor': monitor, 'level': level, 'pid': 1}


FURNITURE = [layer('0x5efa8e8b6a50', 'omarchy-background', 0), layer(BAR, 'omarchy-bar', 2)]
OPEN = FURNITURE + [layer(PANEL, 'nixarchy-pkg-menu', 3)]


def typed(helper):
    return [line for line in helper.sent if line != 'C']


class Layers(Base):
    def test_reads_razers_shape(self):
        with patch.object(host, 'ctl', return_value=json.dumps(RAZER_LAYERS)):
            rows = host.layers()
        self.assertEqual({(r['namespace'], r['level']) for r in rows},
                         {('omarchy-background', 0), ('omarchy-bar', 2), ('nixarchy-pkg-menu', 3)})
        self.assertEqual([r['address'] for r in rows if r['level'] == 3], [PANEL])

    def test_a_failed_query_raises(self):
        with patch.object(host, 'ctl', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                host.layers()

    def test_windows_op_lists_both(self):
        with patch.object(host, 'windows', return_value=[]), patch.object(host, 'layers', return_value=OPEN):
            out = api.run('windows', {})
        self.assertEqual(set(out), {'windows', 'layers', 'generation'})
        self.assertEqual(out['layers'], OPEN)


class TypingIntoASurface(Base):
    def setUp(self):
        super().setUp()
        # Control is granted with the desktop's usual furniture already mapped,
        # which is what the baseline snapshot records (#29).
        with patch.object(host, 'layers', return_value=FURNITURE):
            self.granted = grant()

    def run_on(self, layers, focused, lines=('T hi',), target=PANEL):
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=layers), \
             patch.object(host, 'focused_address', return_value=focused):
            result = control.run_batch(list(lines), self.granted['generation'], helper, window=target)
        return helper, result

    def test_the_panel_alone_at_the_top_with_no_window_focused_is_typed_into(self):
        helper, result = self.run_on(OPEN, None)
        self.assertEqual(helper.sent, ['T hi'])
        self.assertIn('nixarchy-pkg-menu', result['note'])
        self.assertIn('NOT verified', result['note'])

    def test_a_focused_window_no_longer_refuses_but_is_named(self):
        # #29: Hyprland keeps naming the window under an overlay that has taken
        # the keyboard, so demanding "no window focused" made the supported path
        # unreachable. The window is reported instead of refused.
        helper, result = self.run_on(OPEN, WINDOW)
        self.assertEqual(helper.sent, ['T hi'])
        self.assertIn('nixarchy-pkg-menu', result['note'])
        self.assertIn(WINDOW, result['note'])
        self.assertIn('still holds focus', result['note'])

    def test_another_surface_at_the_same_level_refuses_and_names_it(self):
        toast = layer(TOAST, 'notification', 3)
        with self.assertRaises(MirrorError) as caught:
            self.run_on(OPEN + [toast], None)
        self.assertIn('notification', str(caught.exception))

    def test_a_surface_above_refuses(self):
        low = [layer(PANEL, 'launcher', 2), layer(TOAST, 'osd', 3)]
        with self.assertRaises(MirrorError):
            self.run_on(low, None)

    def test_a_surface_below_does_not_refuse(self):
        # The bar sits at level 2, under the panel at 3: that is the normal case.
        helper, _ = self.run_on(OPEN, None)
        self.assertEqual(helper.sent, ['T hi'])

    def test_key_release_is_sent_when_surface_closes_on_keydown(self):
        helper = FakeHelper()
        calls = []

        def layers():
            calls.append(1)
            return OPEN if len(calls) == 1 else FURNITURE

        with patch.object(host, 'layers', side_effect=layers), \
             patch.object(host, 'windows', return_value=[]), \
             patch.object(host, 'focused_address', return_value=WINDOW):
            control.run_batch(['K 27 1', 'K 27 0'], self.granted['generation'], helper,
                              window=PANEL, owners=[0, 0])
        self.assertEqual(helper.sent, ['K 27 1', 'K 27 0'])

    def test_a_closed_surface_is_refused(self):
        without = [l for l in OPEN if l['address'] != PANEL]
        with self.assertRaises(MirrorError):
            self.run_on(without, None)

    def test_an_unreadable_layer_list_never_types_into_a_surface(self):
        # Falls through to #24's check: no window is focused, which is not
        # PANEL, so it refuses. Failing to ask is not permission.
        helper = FakeHelper()
        with patch.object(host, 'layers', side_effect=RuntimeError('boom')), \
             patch.object(host, 'focused_address', return_value=None):
            with self.assertRaises(MirrorError):
                control.run_batch(['T hi'], self.granted['generation'], helper, window=PANEL)
        self.assertEqual(typed(helper), [])

    def test_an_unreadable_focus_is_unavailable(self):
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=OPEN), \
             patch.object(host, 'focused_address', side_effect=RuntimeError('boom')):
            with self.assertRaises(MirrorError) as caught:
                control.run_batch(['T hi'], self.granted['generation'], helper, window=PANEL)
        self.assertEqual(caught.exception.code, 'unavailable')
        self.assertEqual(typed(helper), [])

    def test_a_surface_appearing_mid_batch_stops_the_rest(self):
        helper = FakeHelper()
        calls = []

        def layers():
            calls.append(1)
            return OPEN if len(calls) <= 2 else OPEN + [layer(TOAST, 'notification', 3)]

        with patch.object(host, 'layers', side_effect=layers), \
             patch.object(host, 'focused_address', return_value=None):
            with self.assertRaises(MirrorError):
                control.run_batch(['T a', 'T b', 'T c'], self.granted['generation'], helper, window=PANEL)
        self.assertEqual(typed(helper), ['T a', 'T b'])

    def test_a_tap_line_is_sent_to_a_window_target_and_leaves_nothing_held(self):
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=FURNITURE), \
             patch.object(host, 'focused_address', return_value=WINDOW):
            result = control.run_batch(['P 29 30'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(helper.sent, ['P 29 30'])
        self.assertNotIn('closed', result)

    def test_a_window_target_keeps_24s_path_under_the_usual_furniture(self):
        # The bar and background were mapped when control was granted, so they
        # are not in the way: #24's path is unchanged.
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=FURNITURE), \
             patch.object(host, 'focused_address', return_value=WINDOW):
            result = control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(helper.sent, ['T hi'])
        self.assertIn(WINDOW, result['note'])

    def test_a_window_target_refuses_while_a_new_surface_is_up(self):
        # #29: the panel opened after the grant and may hold the keyboard, and
        # Hyprland cannot be asked. Refuse and name it rather than report the
        # window as the destination.
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=OPEN), \
             patch.object(host, 'focused_address', return_value=WINDOW):
            with self.assertRaises(MirrorError) as caught:
                control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(caught.exception.code, 'wrong_target')
        self.assertIn('nixarchy-pkg-menu', str(caught.exception))
        self.assertEqual([line for line in helper.sent if line != 'C'], [])


class TypingBesideFurniture(Base):
    """#83: a same-level surface mapped since the grant (the notification host) is furniture."""

    NOTIFY = layer(TOAST, 'omarchy-notifications', 3)

    def setUp(self):
        super().setUp()
        with patch.object(host, 'layers', return_value=FURNITURE + [self.NOTIFY]):
            self.granted = grant()

    def run_on(self, layers, lines=('T hi',), target=PANEL):
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=layers), \
             patch.object(host, 'focused_address', return_value=None):
            control.run_batch(list(lines), self.granted['generation'], helper, window=target)
        return helper

    def test_same_level_furniture_does_not_block(self):
        self.assertEqual(self.run_on(OPEN + [self.NOTIFY]).sent, ['T hi'])

    def test_a_newcomer_beside_furniture_still_blocks_and_only_it_is_named(self):
        with self.assertRaises(MirrorError) as caught:
            self.run_on(OPEN + [self.NOTIFY, layer('0x5efa93100000', 'osd', 3)])
        self.assertEqual(caught.exception.code, 'wrong_target')
        self.assertIn('osd', str(caught.exception))
        self.assertNotIn('omarchy-notifications', str(caught.exception))

    def test_furniture_that_left_and_came_back_blocks(self):
        self.assertEqual(self.run_on(OPEN).sent, ['T hi'])  # records the departure
        with self.assertRaises(MirrorError) as caught:
            self.run_on(OPEN + [self.NOTIFY])
        self.assertEqual(caught.exception.code, 'wrong_target')
        self.assertIn('omarchy-notifications', str(caught.exception))

    def test_furniture_above_the_target_blocks(self):
        with self.assertRaises(MirrorError) as caught:
            self.run_on(FURNITURE + [layer(PANEL, 'launcher', 2), self.NOTIFY])
        self.assertEqual(caught.exception.code, 'wrong_target')

    def test_without_a_baseline_every_same_level_surface_blocks(self):
        with patch.object(host, 'layers', side_effect=RuntimeError('boom')):
            self.granted = grant()
        with self.assertRaises(MirrorError) as caught:
            self.run_on(OPEN + [self.NOTIFY])
        self.assertEqual(caught.exception.code, 'wrong_target')


class ReleaseAfterTargetCloses(Base):
    """#68: a key-up whose key-down landed may follow the target's closing."""

    def setUp(self):
        super().setUp()
        # Not a TypingIntoASurface subclass: that would run its tests again here.
        with patch.object(host, 'layers', return_value=FURNITURE):
            self.granted = grant()

    def drive(self, lines, owners, gone_after=None, on_line=None, acks=None,
              windows_error=None, layers_error=None, focus_error=None, still_listed=False):
        """Run WINDOW-targeted lines; after `gone_after` lines are sent the window closes."""
        sent = []
        gone = [1] if gone_after == 0 else []

        def on_cmd(line):
            sent.append(line)
            if gone_after is not None and len(sent) >= gone_after:
                gone.append(1)
            if on_line:
                on_line(line)

        def windows():
            if windows_error and gone:
                raise windows_error
            return [{'address': WINDOW}] if (not gone or still_listed) else []

        def layers():
            if layers_error and gone:
                raise layers_error
            return FURNITURE

        def focused():
            if focus_error and gone:
                raise focus_error
            return '0xother' if gone else WINDOW

        helper = FakeHelper(acks=acks, on_cmd=on_cmd)
        with patch.object(host, 'layers', side_effect=layers), \
             patch.object(host, 'windows', side_effect=windows), \
             patch.object(host, 'focused_address', side_effect=focused):
            try:
                result = control.run_batch(lines, self.granted['generation'], helper,
                                           window=WINDOW, owners=owners)
            except MirrorError as exc:
                return helper, exc
        return helper, result

    def refused(self, helper, exc, sent, code='wrong_target'):
        self.assertIsInstance(exc, MirrorError)
        self.assertEqual(exc.code, code)
        self.assertEqual(typed(helper), sent)
        self.assertEqual(helper.sent[-1], 'C')

    def test_release_after_the_window_closes_is_sent(self):
        helper, result = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1)
        self.assertEqual(helper.sent, ['K 28 1', 'K 28 0'])
        self.assertIs(result['closed'], True)
        self.assertIn('then closed', result['note'])

    def test_a_window_still_listed_is_refused(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1, still_listed=True)
        self.refused(helper, exc, ['K 28 1'])

    def test_an_unmatched_release_is_refused(self):
        helper, exc = self.drive(['K 28 0'], [0], gone_after=0)
        self.refused(helper, exc, [])

    def test_a_windows_read_error_is_refused(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1,
                                 windows_error=RuntimeError('boom'))
        self.refused(helper, exc, ['K 28 1'])

    def test_a_layers_read_error_is_refused(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1,
                                 layers_error=RuntimeError('boom'))
        self.refused(helper, exc, ['K 28 1'])

    def test_a_release_matched_in_a_previous_action_is_refused(self):
        # Pressed in action 0, released in action 1: the reset is the only thing refusing it.
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 1], gone_after=1)
        self.refused(helper, exc, ['K 28 1'])

    def test_a_repeated_code_in_one_action_is_refused(self):
        helper, exc = self.drive(['K 30 1', 'K 30 0', 'K 30 0'], [0, 0, 0], gone_after=2)
        self.refused(helper, exc, ['K 30 1', 'K 30 0'])

    def test_revoked_before_the_release_is_stale(self):
        def revoke(line):
            if line == 'K 28 1':
                control.set_owner('off', 'human')

        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1, on_line=revoke)
        self.refused(helper, exc, ['K 28 1'], code='stale_generation')

    def test_a_rescued_release_the_helper_rejects_is_unavailable(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1, acks=['OK', 'ERR'])
        self.assertIsInstance(exc, MirrorError)
        self.assertEqual(exc.code, 'unavailable')
        self.assertEqual(helper.sent, ['K 28 1', 'K 28 0', 'C'])

    def test_without_owners_nothing_is_rescued(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], None, gone_after=1)
        self.refused(helper, exc, ['K 28 1'])

    def test_a_modifier_released_after_the_close_is_sent_only_within_its_action(self):
        lines = ['K 29 1', 'K 46 1', 'K 46 0', 'K 29 0']
        helper, result = self.drive(lines, [0] * 4, gone_after=2)
        self.assertEqual(helper.sent, lines)
        self.assertIs(result['closed'], True)
        helper, exc = self.drive(lines, [0, 0, 0, 1], gone_after=2)
        self.refused(helper, exc, lines[:3])

    def test_an_unreadable_focus_is_not_rescued(self):
        helper, exc = self.drive(['K 28 1', 'K 28 0'], [0, 0], gone_after=1,
                                 focus_error=RuntimeError('boom'))
        self.refused(helper, exc, ['K 28 1'], code='unavailable')


class CliCanType(Base):
    def test_window_reaches_the_api(self):
        seen = {}

        def run(op, args, by='human'):
            seen.update(op=op, args=args)
            return {'ok': True}

        with patch.object(api, 'run', side_effect=run), patch('builtins.print'):
            cli.main(['input', '--generation', '3', '--window', PANEL,
                      '[{"type":"key","keys":["J"]}]'])
        self.assertEqual(seen['op'], 'input')
        self.assertEqual(seen['args']['window'], PANEL)
        self.assertEqual(seen['args']['generation'], 3)


if __name__ == '__main__':
    unittest.main()
