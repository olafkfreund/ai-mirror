"""`ai-mirror audit`: reading back the log, and saying which empty is which.

The case this exists for is not "does it print lines". It is that an empty
answer must say WHETHER the log is absent or merely has nothing in it:
$XDG_RUNTIME_DIR does not survive a reboot, so "no entries" and "this machine
rebooted since I last looked" are the same file state, and a reader who
cannot tell them apart takes the first for an all-clear (#44).

Needs no desktop. Reads are deliberately unguarded (AGENTS.md), and Base
isolates XDG_RUNTIME_DIR into a temporary directory, so nothing here can
reach the real log.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, cli, control, host, mcp

from test_invariants import Base


def write(*lines):
    path = control.root() / 'audit.jsonl'
    path.write_text(''.join(line + '\n' for line in lines), encoding='utf-8')
    return path


def line(event, **fields):
    return json.dumps({'event': event, 'at': f'2026-09-27T06:0{len(event) % 10}:00+0100', **fields},
                      sort_keys=True)


class Audit(Base):
    def test_entries_come_back_parsed_and_newest_last(self):
        write(line('requested', by='agent'), line('confirmed'), line('off', was='agent'))
        got = control.read_audit()
        self.assertEqual([e['event'] for e in got['entries']], ['requested', 'confirmed', 'off'])
        self.assertEqual(got['entries'][0]['by'], 'agent')
        self.assertEqual(got['source'], 'file')
        self.assertEqual(got['total'], 3)

    def test_a_missing_log_is_not_the_same_as_an_empty_one(self):
        # The whole point of the verb. Both are "no entries"; only one means
        # nothing happened, and the other also means a reboot may have taken
        # the record with it.
        absent = control.read_audit()
        self.assertEqual(absent['source'], 'absent')
        self.assertEqual(absent['entries'], [])

        write()
        empty = control.read_audit()
        self.assertEqual(empty['source'], 'file')
        self.assertEqual(empty['entries'], [])
        self.assertNotEqual(absent['source'], empty['source'])

    def test_the_two_empty_answers_read_differently_to_a_person(self):
        absent = cli.render_audit(control.read_audit())
        write()
        empty = cli.render_audit(control.read_audit())
        self.assertNotEqual(absent, empty)
        for text in (absent, empty):
            self.assertIn('does not survive a', text)

    def test_a_truncated_line_is_skipped_not_fatal(self):
        path = write(line('requested'), '{"event": "conf', line('off'))
        self.assertTrue(path.exists())
        got = control.read_audit()
        self.assertEqual([e['event'] for e in got['entries']], ['requested', 'off'])
        self.assertEqual(got['skipped'], 1)

    def test_the_default_is_the_last_twenty_and_zero_means_all(self):
        write(*[line('off', n=i) for i in range(50)])
        self.assertEqual(len(control.read_audit()['entries']), 20)
        self.assertEqual(control.read_audit(0)['total'], 50)
        self.assertEqual(len(control.read_audit(0)['entries']), 50)
        # the LAST twenty, not the first
        self.assertEqual(control.read_audit()['entries'][-1]['n'], 49)

    def test_api_reports_when_the_log_began(self):
        write(line('requested'))
        self.assertIn('since', api.run('audit'))

    def test_a_proc_stat_without_btime_costs_a_sentence_not_the_answer(self):
        write(line('requested'))
        with patch.object(control, 'boot_time', lambda: None):
            got = api.run('audit')
        self.assertEqual(len(got['entries']), 1)
        self.assertNotIn('since', got)

    def test_audit_is_not_an_mcp_tool(self):
        # Deliberate, and asserted so that completing AGENTS.md's recipe fails
        # a test rather than passing review. The reader is the person deciding
        # whether to trust an agent; handing that agent its own trail is the
        # machinery AGENTS.md says not to add (#44).
        self.assertNotIn('audit', mcp.SPECS)

    def test_audit_does_not_mark_the_bar_as_watched(self):
        # OBSERVING makes a by='agent' call light the bar. There is no agent
        # path here, and adding one would be the MCP decision by the back door.
        self.assertNotIn('audit', api.OBSERVING)

    def test_status_names_the_verb(self):
        # monitors() talks to Hyprland, which the suite deliberately cannot
        # reach; the assertion here is about the pointer, not the monitors.
        with patch.object(host, 'monitors', lambda: []):
            self.assertIn('audit', api.run('status'))


if __name__ == '__main__':
    unittest.main()
