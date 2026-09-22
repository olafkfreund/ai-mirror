"""#24: a keystroke must not land in a window nobody chose."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, control, host, input as input_mod
from ai_mirror.control import MirrorError

from test_invariants import Base, FakeHelper, grant

WINDOW = '0x5d811eac1ea0'
OTHER = '0x5d811e970e00'


def typed(helper):
    """Input lines the helper actually sent. 'C' is cancel's own line, not input."""
    return [line for line in helper.sent if line != 'C']


class FocusedAddress(Base):
    """host.focused_address: a failure is not None, because they mean different things."""

    def test_returns_the_address(self):
        with patch.object(host, 'ctl', return_value=json.dumps({'address': WINDOW})):
            self.assertEqual(host.focused_address(), WINDOW)

    def test_empty_workspace_is_none(self):
        with patch.object(host, 'ctl', return_value='{}'):
            self.assertIsNone(host.focused_address())

    def test_a_failed_query_raises_rather_than_returning_none(self):
        # The distinction the whole guard rests on: "nothing is focused" and
        # "we could not find out" must not collapse into one value.
        with patch.object(host, 'ctl', side_effect=RuntimeError('Hyprland: no')):
            with self.assertRaises(RuntimeError):
                host.focused_address()


class NeedsWindow(Base):
    """Keyboard-ness is a property of the actions, never of the encoded lines."""

    def test_typing_needs_a_window(self):
        self.assertTrue(input_mod.needs_window([{'type': 'type', 'text': 'hi'}]))
        self.assertTrue(input_mod.needs_window([{'type': 'key', 'keys': ['CTRL', 'L']}]))

    def test_a_modified_click_does_not(self):
        # ctrl+click encodes to K/M/B/K -- it LOOKS like keyboard on the wire.
        action = [{'type': 'click', 'x': 1, 'y': 1, 'modifiers': ['CTRL']}]
        self.assertIn('K 29 1', input_mod.encode(action))
        self.assertFalse(input_mod.needs_window(action))


class FocusIsVerified(Base):
    def setUp(self):
        super().setUp()
        self.granted = grant()

    def test_matching_focus_sends_the_keystrokes(self):
        helper = FakeHelper()
        with patch.object(host, 'focused_address', return_value=WINDOW):
            result = control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(helper.sent, ['T hi'])
        self.assertIn('NOT verified', result['note'])

    def test_a_mismatch_sends_nothing_at_all(self):
        # Asserted on the helper, not the message: a guard that refused AFTER
        # typing would pass a message-level assertion with the keystroke landed.
        helper = FakeHelper()
        with patch.object(host, 'focused_address', return_value=OTHER):
            with self.assertRaises(MirrorError) as caught:
                control.run_batch(['T secret'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(typed(helper), [])
        self.assertIn('NOT sent', str(caught.exception))

    def test_an_empty_workspace_refuses(self):
        helper = FakeHelper()
        with patch.object(host, 'focused_address', return_value=None):
            with self.assertRaises(MirrorError):
                control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(typed(helper), [])

    def test_an_unreadable_focus_refuses_rather_than_passing(self):
        helper = FakeHelper()
        with patch.object(host, 'focused_address', side_effect=RuntimeError('boom')):
            with self.assertRaises(MirrorError) as caught:
                control.run_batch(['T hi'], self.granted['generation'], helper, window=WINDOW)
        self.assertEqual(typed(helper), [])
        self.assertEqual(caught.exception.code, 'unavailable')

    def test_focus_moving_mid_batch_stops_the_rest(self):
        helper = FakeHelper()
        seen = []

        def focus():
            seen.append(1)
            return WINDOW if len(seen) <= 2 else OTHER

        with patch.object(host, 'focused_address', side_effect=focus):
            with self.assertRaises(MirrorError):
                control.run_batch(['T a', 'T b', 'T c'], self.granted['generation'],
                                  helper, window=WINDOW)
        self.assertEqual(typed(helper), ['T a', 'T b'])

    def test_pointer_batches_are_untouched(self):
        helper = FakeHelper()
        with patch.object(host, 'focused_address', side_effect=AssertionError('must not be called')):
            control.run_batch(['M 1 1'], self.granted['generation'], helper)
        self.assertEqual(helper.sent, ['M 1 1'])


class ApiRequiresWindowForTyping(Base):
    def setUp(self):
        super().setUp()
        self.granted = grant()

    def test_typing_without_a_window_is_refused_with_the_remedy(self):
        with self.assertRaises(MirrorError) as caught:
            api.run('input', {'actions': [{'type': 'type', 'text': 'hi'}],
                              'generation': self.granted['generation']}, by='agent')
        message = str(caught.exception)
        self.assertIn('window', message)
        self.assertIn('call windows', message)

    def test_a_pointer_action_still_needs_no_window(self):
        # run_batch binds helper=HELPER as a default at def time, so patching
        # control.HELPER would not reach it. Record the call instead.
        seen = {}

        def record(lines, generation, helper=None, window=None, owners=None):
            seen.update(lines=lines, window=window)
            return {'ok': True}

        with patch.object(control, 'run_batch', record):
            api.run('input', {'actions': [{'type': 'move', 'x': 5, 'y': 5}],
                              'generation': self.granted['generation']}, by='agent')
        self.assertEqual(seen['lines'], ['M 5 5'])
        self.assertIsNone(seen['window'])


class SchemaAcceptsWindow(Base):
    def test_validate_accepts_window(self):
        from ai_mirror import mcp
        mcp.validate('input', {'actions': [{'type': 'type', 'text': 'hi'}], 'window': WINDOW})

    def test_validate_still_rejects_unknown_keys(self):
        from ai_mirror import mcp
        with self.assertRaises(ValueError):
            mcp.validate('input', {'actions': [{'type': 'move', 'x': 1, 'y': 1}], 'windoww': WINDOW})


if __name__ == '__main__':
    unittest.main()
