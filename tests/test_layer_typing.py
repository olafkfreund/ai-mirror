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


OPEN = [layer('0x5efa8e8b6a50', 'omarchy-background', 0), layer(BAR, 'omarchy-bar', 2),
        layer(PANEL, 'nixarchy-pkg-menu', 3)]


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
        self.assertEqual(set(out), {'windows', 'layers'})
        self.assertEqual(out['layers'], OPEN)


class TypingIntoASurface(Base):
    def setUp(self):
        super().setUp()
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

    def test_a_focused_window_refuses_and_sends_nothing(self):
        with self.assertRaises(MirrorError) as caught:
            self.run_on(OPEN, WINDOW)
        self.assertIn('NOT sent', str(caught.exception))

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

    def test_a_window_target_keeps_24s_path(self):
        helper = FakeHelper()
        with patch.object(host, 'layers', return_value=OPEN), \
             patch.object(host, 'focused_address', return_value=WINDOW):
            result = control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(helper.sent, ['T hi'])
        self.assertIn(WINDOW, result['note'])


class CliCanType(Base):
    def test_window_reaches_the_api(self):
        seen = {}

        def run(op, args):
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
