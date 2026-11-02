"""What happened between calls (#95)."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import events

from test_invariants import Base

ME = {'pid': 1, 'start': 2}


def state(owner='agent', held_by=ME, generation=1):
    return {'owner': owner, 'held_by': held_by, 'generation': generation}


class Pure(Base):
    def test_parse_splits_once(self):
        self.assertEqual(events.parse('activewindow>>foot,a>>b\n'), ('activewindow', 'foot,a>>b'))

    def test_parse_drops_line_without_separator(self):
        self.assertIsNone(events.parse('nothing here\n'))

    def test_parse_caps_data(self):
        self.assertEqual(len(events.parse('x>>' + 'a' * 1000)[1]), 300)

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

    def feed(self, r, line, st):
        with patch.object(events.control, 'SERVER', ME), \
                patch.object(events.host, 'windows', return_value=[]):
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
        rows = [{'address': '0xaa', 'class': 'KeePassXC'}]
        with patch.object(events.control, 'SERVER', ME), \
                patch.object(events.host, 'windows', return_value=rows):
            events.feed('windowtitlev2>>aa,Vault', state(), r)
            events.feed('openwindow>>bb,1,pinentry,x', state(), r)
            events.feed('windowtitlev2>>bb,Enter', state(), r)
        got = [e['data'] for e in r.since(0, 10)['events']]
        self.assertIn('withheld', got[0])
        self.assertIn('withheld', got[2])
