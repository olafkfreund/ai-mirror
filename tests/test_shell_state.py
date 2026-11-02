"""#99: the shell's state, read through a fixed allowlist and nothing else."""
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, mcp, shell

from test_invariants import Base


def block(name, pid, display):
    return (f'Instance {name}:\n  Process ID: {pid}\n  Shell ID: abc\n'
            f'  Config path: /x/shell.qml\n  Display connection: {display}\n  Launch time: now\n')


def done(out='', code=0):
    return SimpleNamespace(returncode=code, stdout=out)


class Fake:
    """Stands in for subprocess.run in shell: `qs list --all`, then `qs ipc ... call`."""

    def __init__(self, listing, answers=None, fail=()):
        self.listing, self.answers, self.fail, self.argv = listing, answers or {}, set(fail), []

    def __call__(self, argv, **kw):
        self.argv.append(argv)
        if argv[:3] == ['qs', 'list', '--all']:
            return done(self.listing)
        pair = (argv[5], argv[6])
        if pair in self.fail:
            raise shell.subprocess.TimeoutExpired(argv, 2)
        return done(self.answers.get(pair, 'true'))


ONE = block('a', 42, 'wayland/wayland-1')


class ShellState(Base):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-1'})
        env.start()
        self.addCleanup(env.stop)

    def run_state(self, fake):
        with patch.object(shell.subprocess, 'run', fake):
            return shell.state()

    def test_argv_comes_only_from_reads(self):
        fake = Fake(ONE)
        self.run_state(fake)
        calls = [a for a in fake.argv if a[:3] != ['qs', 'list', '--all']]
        self.assertEqual(len(calls), len(shell.READS))
        for argv in calls:
            self.assertEqual(argv[:5], ['qs', 'ipc', '--pid', '42', 'call'])
            self.assertEqual(len(argv), 7)
            self.assertIn((argv[5], argv[6]), shell.READS.values())

    def test_no_read_can_change_state(self):
        bad = {'show', 'open', 'toggle', 'call', 'summon', 'close', 'hide', 'refresh'}
        for target, function in shell.READS.values():
            self.assertNotIn(function, bad)
            self.assertFalse(function.startswith('set'), function)

    def test_instance(self):
        def pid(listing):
            with patch.object(shell.subprocess, 'run', Fake(listing)):
                return shell._instance()
        self.assertEqual(pid(ONE), 42)
        self.assertIsNone(pid(''))
        self.assertIsNone(pid(ONE + block('b', 43, 'wayland/wayland-1')))
        self.assertEqual(pid(ONE + block('b', 43, 'wayland/wayland-9')), 42)
        self.assertIsNone(pid(block('b', 43, 'wayland/wayland-9')))

    def test_parse(self):
        self.assertEqual(shell._parse('[]'), [])
        self.assertEqual(shell._parse('{"a":1}\n'), {'a': 1})
        self.assertIs(shell._parse('off'), False)
        self.assertIs(shell._parse('on'), True)
        self.assertIs(shell._parse('true'), True)
        self.assertEqual(shell._parse('4'), 4)
        self.assertEqual(shell._parse(' closed \n'), 'closed')

    def test_media_is_reduced(self):
        out = shell._media({'identity': 'Spotify', 'playing': True, 'title': 'T', 'artist': 'A',
                            'album': 'B', 'artUrl': 'http://x'})
        self.assertEqual(out, {'player': 'Spotify', 'playing': True})

    def test_private_call_title_is_withheld_and_an_ordinary_one_kept(self):
        private = shell._meeting({'callApp': 'firefox', 'callTitle': 'Meet — Mozilla Firefox Private Browsing'})
        self.assertIn('withheld', private['callTitle'])
        ordinary = shell._meeting({'callApp': 'zoom', 'callTitle': 'Standup'})
        self.assertEqual(ordinary['callTitle'], 'Standup')

    def test_a_non_dict_reduces_to_unavailable(self):
        self.assertEqual(shell._media('oops'), 'unavailable')
        self.assertEqual(shell._meeting('oops'), 'unavailable')

    def test_one_failing_target_only_loses_its_field(self):
        out = self.run_state(Fake(ONE, fail={('lock', 'isLocked')}))
        self.assertEqual(out['locked'], 'unavailable')
        self.assertIs(out['dnd'], True)
        self.assertEqual(set(out), set(shell.READS))

    def test_empty_output_is_unavailable(self):
        fake = Fake(ONE)
        run = lambda argv, **kw: done('') if argv[-1] == 'count' else fake(argv, **kw)
        with patch.object(shell.subprocess, 'run', run):
            self.assertEqual(shell.state()['notifications'], 'unavailable')

    def test_no_instance_makes_everything_unavailable(self):
        out = self.run_state(Fake(''))
        self.assertEqual({k: v for k, v in out.items() if k != 'note'},
                         dict.fromkeys(shell.READS, 'unavailable'))
        self.assertEqual(out['note'], 'no Quickshell instance on this display')

    def test_missing_qs_means_no_instance(self):
        with patch.object(shell.subprocess, 'run', side_effect=FileNotFoundError('qs')):
            self.assertIn('note', shell.state())

    def test_registered_as_a_read(self):
        self.assertIn('shell_state', mcp.READ_ONLY)
        self.assertIn('shell_state', api.OBSERVING)
        self.assertEqual(cli.build_parser().parse_args(['shell_state']).op, 'shell_state')


if __name__ == '__main__':
    unittest.main()
