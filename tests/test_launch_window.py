"""`launch` reports the window it opened (#54)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from unittest.mock import patch

from ai_mirror import api, cli, guard, host, mcp

from test_invariants import Base, grant


class LaunchGuard(Base):
    def test_unstubbed_launch_is_blocked(self):
        grant()
        with patch.object(host, 'windows', lambda timeout=10: []), self.assertRaises(guard.Blocked):
            api.run('launch', {'argv': ['true']}, by='agent')


def row(addr, **over):
    return {'address': addr, 'class': 'foot', 'title': 't', **over}


class Launch(Base):
    def run_launch(self, seq, args=None, spawn=True):
        """seq: scripted host.windows results (an Exception is raised); the last repeats."""
        grant()
        self.spawns, self.budgets, calls = 0, [], iter(seq)
        last = []

        def windows(timeout=10):
            self.budgets.append(timeout)
            item = next(calls, None) or (last[0] if last else [])
            last[:] = [item]
            if isinstance(item, Exception):
                raise item
            return item

        def spawn_(argv):
            self.spawns += 1
            return 4242

        with patch.object(host, 'windows', windows), patch.object(api, '_spawn', spawn_):
            return api.run('launch', {'argv': ['foot'], **(args or {})}, by='agent')

    def test_one_new_window(self):
        r = self.run_launch([[row('0x1')], [row('0x1'), row('0x2', **{'class': 'x', 'title': 'y'})]])
        self.assertEqual((r['pid'], r['window'], r['class'], r['title']), (4242, '0x2', 'x', 'y'))
        self.assertEqual(self.spawns, 1)

    def test_two_new_windows(self):
        r = self.run_launch([[], [row('0x1'), row('0x2')]])
        self.assertEqual([c['address'] for c in r['candidates']], ['0x1', '0x2'])
        self.assertNotIn('window', r)

    def test_none_gives_note(self):
        r = self.run_launch([[row('0x1')]], {'timeout': 0.1})
        self.assertTrue(r['ok'])
        self.assertIn('do not launch again', r['note'])
        self.assertNotIn('window', r)

    def test_read_failing_after_spawn_never_raises(self):
        r = self.run_launch([[], OSError('boom')], {'timeout': 0.1})
        self.assertTrue(r['ok'])
        self.assertIn('boom', r['note'])
        self.assertIn('do not launch again', r['note'])
        self.assertEqual(self.spawns, 1)

    def test_read_failing_before_spawn_raises(self):
        with self.assertRaises(OSError):
            self.run_launch([OSError('boom')])
        self.assertEqual(self.spawns, 0)

    def test_bad_argv_spawns_nothing(self):
        with self.assertRaises(ValueError):
            self.run_launch([[]], {'argv': []})
        self.assertEqual(self.spawns, 0)

    def test_timeout_zero_looks_once(self):
        r = self.run_launch([[row('0x1')]], {'timeout': 0})
        self.assertIn('note', r)
        self.assertEqual(len(self.budgets), 2)  # the read before the spawn, then one look

    def test_bad_timeout_spawns_nothing(self):
        # The CLI reaches api.run without MCP's schema, so _timeout is the check.
        for bad in (float('nan'), -1, 'soon'):
            with self.subTest(bad), self.assertRaises(ValueError):
                self.run_launch([[]], {'timeout': bad})
            self.assertEqual(self.spawns, 0)

    def test_poll_reads_get_the_budget(self):
        self.run_launch([[]], {'timeout': 0.1})
        self.assertTrue(all(b <= 0.1 for b in self.budgets[1:]), self.budgets)

    def test_mcp_timeout_schema(self):
        mcp.validate('launch', {'argv': ['a'], 'timeout': 0})
        for bad in (31, float('nan')):
            with self.assertRaises(ValueError):
                mcp.validate('launch', {'argv': ['a'], 'timeout': bad})

    def test_cli_parse(self):
        a = cli.build_parser().parse_args(['launch', '--timeout', '2', '--', 'foot'])
        self.assertEqual((a.timeout, a.argv), (2.0, ['--', 'foot']))


if __name__ == '__main__':
    unittest.main()
