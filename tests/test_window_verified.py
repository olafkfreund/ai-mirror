"""`window` reads, acts, then confirms against the compositor (#53).

The dispatch returning says nothing happened, so the result must say whether
it did, and must not dispatch at all when the state already holds. Needs no
desktop: `host.windows`, `host.focused_address` and `host.ctl` are stubbed, and
Base arms the guard so a stray dispatch would raise rather than move a window.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, control, host, mcp

from test_invariants import Base, grant

ADDR = '0x55d1c2a3'


def row(**over):
    base = {'address': ADDR, 'class': 'foot', 'title': 't', 'at': [0, 0], 'size': [800, 600],
            'monitor': 0, 'floating': True, 'fullscreen': 0, 'workspace': '1', 'pid': 7, 'focusHistoryID': 1}
    return {**base, **over}


class WindowVerified(Base):
    def world(self, rows, focused=None, effect=None):
        """Stub the compositor. `effect(state)` runs on each dispatch."""
        self.state = {'rows': rows, 'focused': focused}
        self.dispatches = []

        def ctl(*argv, **kw):
            if argv[0] != 'dispatch':  # a read the gate makes; not under test
                return '{}'
            self.dispatches.append(argv)
            if effect:
                effect(self.state)
            return 'ok'
        for name, fake in (('windows', lambda: [dict(r) for r in self.state['rows']]),
                           ('focused_address', lambda: self.state['focused']),
                           ('ctl', ctl)):
            p = patch.object(host, name, fake)
            p.start()
            self.addCleanup(p.stop)
        grant()

    def win(self, **args):
        return api.run('window', {'address': ADDR, 'timeout': 0.1, **args}, by='agent')

    def confirmed(self, args, rows, effect):
        self.world(rows, None, effect)
        got = self.win(**args)
        self.assertEqual(len(self.dispatches), 1)
        self.assertTrue(got['ok'])
        return got

    def test_each_action_is_confirmed_with_one_dispatch(self):
        def set_(**kw):
            return lambda s: s['rows'][0].update(kw)
        cases = [
            ({'action': 'focus'}, [row()], lambda s: s.update(focused=ADDR)),
            ({'action': 'close'}, [row()], lambda s: s['rows'].clear()),
            ({'action': 'float'}, [row()], set_(floating=False)),
            ({'action': 'float', 'enabled': False}, [row()], set_(floating=False)),
            ({'action': 'workspace', 'workspace': '3'}, [row()], set_(workspace='3')),
            ({'action': 'resize', 'w': 300, 'h': 200}, [row()], set_(size=[300, 200])),
            ({'action': 'fullscreen'}, [row()], set_(fullscreen=1)),
        ]
        for args, rows, effect in cases:
            with self.subTest(args):
                got = self.confirmed(args, rows, effect)
                self.assertIs(got['verified'], True)
                self.assertIs(got['changed'], True)
                self.assertEqual(got['before'], row())
                if args['action'] == 'close':
                    self.assertIsNone(got['after'])

    def test_a_state_that_never_changes_is_not_confirmed(self):
        self.world([row()])
        with self.assertRaises(control.MirrorError) as e:
            self.win(action='workspace', workspace='3')
        self.assertEqual(e.exception.code, 'not_confirmed')
        self.assertEqual(e.exception.details['before'], row())
        self.assertEqual(e.exception.details['after'], row())
        self.assertIn('waited_ms', e.exception.details)
        self.assertEqual(len(self.dispatches), 1)

    def test_what_already_holds_sends_nothing(self):
        cases = [
            ({'action': 'focus'}, {'focused': ADDR}),
            ({'action': 'float', 'enabled': True}, {}),
            ({'action': 'workspace', 'workspace': '1'}, {}),
            ({'action': 'resize', 'w': 800, 'h': 600}, {}),
        ]
        for args, extra in cases:
            with self.subTest(args):
                self.world([row()], **extra)
                got = self.win(**args)
                self.assertEqual(self.dispatches, [])
                self.assertIs(got['changed'], False)
                self.assertIs(got['verified'], True)

    def test_unknown_address_dispatches_nothing(self):
        self.world([row(address='0xabc')])
        with self.assertRaises(control.MirrorError) as e:
            self.win(action='close')
        self.assertEqual(e.exception.code, 'no_such_window')
        self.assertEqual(self.dispatches, [])

    def test_resize_and_center_refuse_a_tiled_window(self):
        for args in ({'action': 'resize', 'w': 1, 'h': 1}, {'action': 'center'}):
            with self.subTest(args):
                self.world([row(floating=False)])
                with self.assertRaises(control.MirrorError) as e:
                    self.win(**args)
                self.assertEqual(e.exception.code, 'invalid')
                self.assertEqual(self.dispatches, [])

    def test_float_enabled_twice_dispatches_once(self):
        self.world([row(floating=False)], effect=lambda s: s['rows'][0].update(floating=True))
        self.win(action='float', enabled=True)
        self.win(action='float', enabled=True)
        self.assertEqual(len(self.dispatches), 1)

    def test_a_failed_read_after_dispatch_is_unavailable(self):
        def boom(s):
            def fail():
                raise OSError('hyprctl gone')
            patch.object(host, 'windows', fail).start()
            self.addCleanup(patch.stopall)
        self.world([row()], effect=boom)
        with self.assertRaises(control.MirrorError) as e:
            self.win(action='close')
        self.assertEqual(e.exception.code, 'unavailable')
        self.assertIn('hyprctl gone', str(e.exception))
        self.assertEqual(e.exception.details['before'], row())

    def test_center_is_read_once_and_unverified(self):
        self.world([row()], effect=lambda s: s['rows'][0].update(at=[5, 5]))
        got = self.win(action='center')
        self.assertIsNone(got['verified'])
        self.assertIs(got['changed'], True)

    def test_center_on_a_window_that_closes_is_not_confirmed(self):
        self.world([row()], effect=lambda s: s['rows'].clear())
        with self.assertRaises(control.MirrorError) as e:
            self.win(action='center')
        self.assertEqual(e.exception.code, 'not_confirmed')
        self.assertIsNone(e.exception.details['after'])

    def test_rows_carry_pid(self):
        reply = json.dumps([{'address': ADDR, 'class': 'c', 'title': 't', 'at': [0, 0], 'size': [1, 1],
                             'monitor': 0, 'floating': True, 'fullscreen': 0, 'pid': 301556,
                             'workspace': {'name': '1'}}])
        with patch.object(host, 'ctl', lambda *a, **k: reply):
            self.assertEqual(host.windows()[0]['pid'], 301556)

    def test_enabled_must_be_a_boolean(self):
        self.world([row()])
        with self.assertRaises(ValueError):
            self.win(action='float', enabled='yes')
        self.assertEqual(self.dispatches, [])

    def test_the_mcp_failure_carries_the_code(self):
        self.world([row()])
        got = mcp.call_tool('window', {'action': 'workspace', 'address': ADDR,
                                       'workspace': '3', 'timeout': 0.1})
        self.assertTrue(got['isError'])
        self.assertEqual(json.loads(got['content'][0]['text'])['code'], 'not_confirmed')
        bad = mcp.call_tool('window', {'action': 'float', 'address': ADDR, 'timeout': float('nan')})
        self.assertTrue(bad['isError'])


if __name__ == '__main__':
    unittest.main()
