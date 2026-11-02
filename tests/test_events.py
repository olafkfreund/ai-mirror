"""What happened between calls (#95)."""
from pathlib import Path
import json
import socket
from types import SimpleNamespace
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, events, mcp

from test_invariants import Base

ME = {'pid': 1, 'start': 2}


def state(owner='agent', held_by=ME, generation=1):
    return {'owner': owner, 'held_by': held_by, 'generation': generation}


class Pure(Base):
    def test_parse_splits_once(self):
        self.assertEqual(events.parse('activewindow>>foot,a>>b\n'), ('activewindow', 'foot,a>>b'))

    def test_parse_drops_line_without_separator(self):
        self.assertIsNone(events.parse('nothing here\n'))

    def test_a_long_private_title_is_withheld_and_stored_capped(self):
        # The marker sits at the end of a long title: redacting after the cap missed it (#95 review).
        r = events.Recorder()
        line = 'openwindow>>5a,3,firefox,' + 'p' * 280 + ' — Mozilla Firefox Private Browsing'
        with patch.object(events.control, 'SERVER', ME), patch.object(events, 'seed', return_value={}):
            events.feed(line, state(), r)
        data = r.since(0, 1)['events'][0]['data']
        self.assertIn('withheld', data)
        self.assertNotIn('ppp', data)
        r.add('x', 'a' * 1000)
        self.assertEqual(len(r.since(1, 1)['events'][0]['data']), 300)

    def test_seed_asks_hyprctl_directly_not_through_host(self):
        # host.windows() retries through host.resolve(), whose on_switch stops HELPER (#95 review).
        out = SimpleNamespace(stdout='[{"address": "0xab", "class": "foot"}]')
        with patch.object(events.subprocess, 'run', return_value=out), \
                patch.object(events.host, 'windows', side_effect=AssertionError('host.windows')):
            self.assertEqual(events.seed(), {'ab': 'foot'})

    def test_redact_openwindow_title(self):
        out = events.redact('openwindow', '1a,2,KeePassXC,Vault, main', {})
        self.assertEqual(out, '1a,2,KeePassXC,<withheld: a password manager>')

    def test_redact_titlev2_uses_class_map(self):
        classes = {'1a': 'KeePassXC'}
        out = events.redact('windowtitlev2', '0x1a,Vault', classes)
        self.assertEqual(out, '0x1a,<withheld: a password manager>')

    def test_redact_keeps_ordinary(self):
        self.assertEqual(events.redact('openwindow', '1a,2,foot,~', {}), '1a,2,foot,~')
        self.assertEqual(events.redact('windowtitlev2', '1a,~', {'1a': 'foot'}), '1a,~')

    def test_redact_activewindow(self):
        self.assertIn('withheld', events.redact('activewindow', 'KeePassXC,x,y', {}))


class Recording(Base):
    def test_since_order_limit_and_empty(self):
        r = events.Recorder()
        self.assertEqual(r.since(0, 10), {'events': [], 'next': 0, 'dropped': False})
        for i in range(5):
            r.add('e', str(i))
        got = r.since(0, 3)
        self.assertEqual([e['seq'] for e in got['events']], [1, 2, 3])
        self.assertEqual(got['next'], 3)
        self.assertEqual(r.since(5, 3), {'events': [], 'next': 5, 'dropped': False})

    def test_dropped_after_overflow(self):
        r = events.Recorder()
        for _ in range(600):
            r.add('e', '')
        self.assertTrue(r.since(0, 5)['dropped'])
        self.assertFalse(r.since(r.cursor() - 10, 5)['dropped'])

    def test_a_later_grant_starts_clean_and_a_future_cursor_is_dropped(self):
        r = events.Recorder()
        r.clear(1)
        for _ in range(10):
            r.add('e', '')
        r.clear(None)
        r.clear(2)
        r.add('new', '')
        got = r.since(0, 10)
        self.assertEqual(([e['event'] for e in got['events']], got['dropped']), (['new'], False))
        self.assertTrue(r.since(1000, 10)['dropped'])  # a cursor from another server life

    def feed(self, r, line, st):
        with patch.object(events.control, 'SERVER', ME), \
                patch.object(events, 'seed', return_value={}):
            events.feed(line, st, r)

    def test_off_records_nothing(self):
        r = events.Recorder()
        self.feed(r, 'a>>b', state(owner='off'))
        self.assertEqual(r.cursor(), 0)

    def test_other_server_records_nothing(self):
        r = events.Recorder()
        self.feed(r, 'a>>b', state(held_by={'pid': 9, 'start': 9}))
        self.assertEqual(r.cursor(), 0)

    def test_a_cli_grant_is_not_ours_without_a_server(self):
        # A CLI grant has held_by None, and so does a process that never registered.
        with patch.object(events.control, 'SERVER', None):
            self.assertFalse(events.held(state(held_by=None)))

    def test_records_and_clears_on_new_generation(self):
        r = events.Recorder()
        self.feed(r, 'a>>b', state())
        self.feed(r, 'c>>d', state())
        self.assertEqual(len(r.since(0, 10)['events']), 2)
        self.feed(r, 'e>>f', state(generation=2))
        got = r.since(0, 10)
        self.assertEqual([e['event'] for e in got['events']], ['e'])
        self.assertEqual(got['events'][0]['seq'], 3)  # seq never goes back

    def test_clears_on_loss_of_control(self):
        r = events.Recorder()
        self.feed(r, 'a>>b', state())
        self.feed(r, 'c>>d', state(owner='off'))
        self.assertEqual(r.since(0, 10)['events'], [])
        self.assertIsNone(r.generation)

    def test_class_map_from_seed_and_openwindow(self):
        r = events.Recorder()
        with patch.object(events.control, 'SERVER', ME), \
                patch.object(events, 'seed', return_value={'aa': 'KeePassXC'}):
            events.feed('windowtitlev2>>aa,Vault', state(), r)
            events.feed('openwindow>>bb,1,pinentry,x', state(), r)
            events.feed('windowtitlev2>>bb,Enter', state(), r)
        got = [e['data'] for e in r.since(0, 10)['events']]
        self.assertIn('withheld', got[0])
        self.assertIn('withheld', got[2])


class Reader(Base):
    def setUp(self):
        super().setUp()
        for target, value in (('SERVER', ME), ('_load', lambda: state())):
            p = patch.object(events.control, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(events, 'seed', return_value={})
        p.start()
        self.addCleanup(p.stop)

    def test_pump_reads_lines_split_across_chunks_until_eof(self):
        a, b = socket.socketpair()
        r = events.Recorder()
        b.sendall(b'one>>1\ntwo>')
        b.sendall(b'>2\nthree>>3\n')
        b.close()
        self.addCleanup(a.close)
        self.assertIsNone(events.pump(a, r))
        self.assertEqual([e['event'] for e in r.since(0, 10)['events']], ['one', 'two', 'three'])

    def test_session_stores_a_gap_when_recording(self):
        a, b = socket.socketpair()
        r = events.Recorder()
        b.sendall(b'one>>1\n')
        b.close()
        events._session(r, connect=lambda: a)
        self.assertEqual(r.since(0, 10)['events'][-1]['event'], 'gap')

    def test_session_stores_no_gap_when_not_recording(self):
        a, b = socket.socketpair()
        r = events.Recorder()
        b.close()
        events._session(r, connect=lambda: a)
        self.assertEqual(r.cursor(), 0)


class Tool(Base):
    def test_events_is_mcp_only_and_read_only(self):
        self.assertIn('events', [t['name'] for t in mcp.TOOLS])
        self.assertIn('events', mcp.READ_ONLY)
        self.assertIn('events', api.OBSERVING)
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            cli.build_parser().parse_args(['events'])

    def run_events(self, running=True, connected=True, st=None, rec=None, **args):
        with patch.object(events, 'RUNNING', running), patch.object(events, 'CONNECTED', connected), \
                patch.object(events, 'RECORDER', rec or events.Recorder()), \
                patch.object(events.control, 'SERVER', ME), \
                patch.object(events.control, '_load', lambda: st or state(owner='off')):
            return api.run('events', args, by='agent')

    def code(self, **kw):
        with self.assertRaises(api.MirrorError) as ctx:
            self.run_events(**kw)
        return ctx.exception.code

    def test_unavailable_when_reader_not_running(self):
        self.assertEqual(self.code(running=False), 'unavailable')

    def test_unavailable_when_the_socket_is_not_connected(self):
        self.assertEqual(self.code(connected=False), 'unavailable')

    def test_not_owner_when_not_held(self):
        self.assertEqual(self.code(), 'not_owner')

    def test_returns_events_when_held(self):
        rec = events.Recorder()
        rec.clear(1)
        rec.add('a', 'b')
        got = self.run_events(st=state(), rec=rec)
        self.assertEqual(set(got), {'events', 'next', 'dropped', 'generation'})
        self.assertEqual((len(got['events']), got['generation']), (1, 1))

    def test_new_grant_before_first_event_returns_empty(self):
        rec = events.Recorder()
        rec.clear(1)
        rec.add('old', 'x')
        got = self.run_events(st=state(generation=2), rec=rec)
        self.assertEqual(got, {'events': [], 'next': 1, 'dropped': False, 'generation': 2})

    def test_bad_arguments_are_refused(self):
        for bad in ({'since': -1}, {'limit': 0}, {'limit': 513}, {'since': True}):
            with self.assertRaises(ValueError):
                self.run_events(st=state(), rec=self.held_rec(), **bad)

    def held_rec(self):
        rec = events.Recorder()
        rec.clear(1)
        return rec


class Caused(Base):
    def call(self, recording):
        rec = events.Recorder()
        if recording:
            rec.clear(1)

        def run(name, args, by):
            rec.add('workspacev2', '2,2')
            return {'ok': True}
        with patch.object(mcp.events, 'RECORDER', rec), patch.object(mcp.api, 'run', run):
            got = mcp.call_tool('input', {'generation': 1, 'actions': [{'type': 'key', 'keys': ['A']}]})
        return json.loads(got['content'][0]['text'])

    def test_result_carries_events_while_recording(self):
        got = self.call(True)
        self.assertEqual(got['events']['list'][0]['event'], 'workspacev2')
        self.assertEqual(got['events']['next'], 1)

    def test_no_events_key_when_not_recording(self):
        self.assertNotIn('events', self.call(False))
