"""#81: ai-mirror finds the live Hyprland itself after a restart."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, control, guard, host, index

from test_invariants import Base, grant

SIG = host.SIG
LIVE = 'live_1_2'
LOST = "Couldn't connect to /run/user/1000/hypr/old/.socket.sock"


def done(out='', err='', code=0):
    return subprocess.CompletedProcess([], code, out, err)


def instances(*names):
    return done(json.dumps([{'instance': n, 'wl_socket': 'wayland-1'} for n in names]))


class Fake:
    """subprocess.run keyed on argv; `hyprctl` answers go in order, after which the last repeats."""

    def __init__(self, hyprctl, listed=(LIVE,), systemd=''):
        self.hyprctl, self.listed, self.systemd = list(hyprctl), listed, systemd
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[:2] == ['hyprctl', 'instances']:
            return instances(*self.listed)
        if argv[0] == 'systemctl':
            return done(self.systemd)
        if len(self.hyprctl) > 1:
            return self.hyprctl.pop(0)
        return self.hyprctl[0]

    def count(self, *prefix):
        return sum(c[:len(prefix)] == list(prefix) for c in self.calls)


class Resolve(Base):
    def setUp(self):
        super().setUp()
        self.switches = []
        host.on_switch = lambda old, new: self.switches.append((old, new))
        host.verified = False
        self.addCleanup(setattr, host, 'on_switch', None)
        self.addCleanup(setattr, host, 'verified', False)

    def run_ctl(self, fake, sig='old_1_1', *args):
        env = {SIG: sig} if sig is not None else {}
        with patch.dict(os.environ, env), patch.object(subprocess, 'run', fake):
            if sig is None:
                os.environ.pop(SIG, None)
            try:
                return host.ctl(*(args or ('monitors', '-j'))), os.environ.get(SIG)
            except RuntimeError as exc:
                return exc, os.environ.get(SIG)

    def test_a_stale_signature_is_replaced_and_the_call_retried(self):
        fake = Fake([done(err=LOST, code=1), done('[]')])
        out, sig = self.run_ctl(fake)
        self.assertEqual((out, sig), ('[]', LIVE))
        self.assertEqual(self.switches, [('old_1_1', LIVE)])
        self.assertEqual(fake.count('hyprctl', 'monitors'), 2)
        self.assertTrue(host.verified)

    def test_an_unset_signature_is_found(self):
        fake = Fake([done(err='HYPRLAND_INSTANCE_SIGNATURE was not set', code=1), done('[]')])
        out, sig = self.run_ctl(fake, None)
        self.assertEqual((out, sig), ('[]', LIVE))
        self.assertEqual(self.switches, [(None, LIVE)])

    def test_the_wayland_display_follows_the_instance(self):
        with patch.object(subprocess, 'run', Fake([])), \
             patch.dict(os.environ, {SIG: 'old_1_1', 'WAYLAND_DISPLAY': 'wayland-0'}):
            host.resolve()
            self.assertEqual(os.environ['WAYLAND_DISPLAY'], 'wayland-1')

    def test_the_systemd_value_wins_among_several(self):
        fake = Fake([done(err=LOST, code=1), done('[]')], listed=('a_1_1', 'b_2_2'),
                    systemd='PATH=/x\nHYPRLAND_INSTANCE_SIGNATURE=b_2_2\n')
        self.assertEqual(self.run_ctl(fake)[1], 'b_2_2')

    def test_the_inherited_value_wins_when_it_is_listed(self):
        fake = Fake([done(err=LOST, code=1), done('[]')], listed=('a_1_1', 'b_2_2'),
                    systemd='HYPRLAND_INSTANCE_SIGNATURE=b_2_2\n')
        with patch.object(subprocess, 'run', fake), patch.dict(os.environ, {SIG: 'a_1_1'}):
            self.assertIsNone(host.resolve())
            self.assertEqual(os.environ[SIG], 'a_1_1')
        self.assertEqual(self.switches, [])

    def test_several_and_no_rule_refuses_and_changes_nothing(self):
        fake = Fake([done(err=LOST, code=1)], listed=('a_1_1', 'b_2_2'), systemd='')
        out, sig = self.run_ctl(fake)
        self.assertIsInstance(out, RuntimeError)
        self.assertIn('2 Hyprland instances are running (a_1_1, b_2_2)', str(out))
        self.assertIn('set HYPRLAND_INSTANCE_SIGNATURE to the one to drive', str(out))
        self.assertEqual(sig, 'old_1_1')
        self.assertEqual(self.switches, [])

    def test_none_running_says_so(self):
        out, sig = self.run_ctl(Fake([done(err=LOST, code=1)], listed=()))
        self.assertIn('Hyprland is not running for this user', str(out))
        self.assertEqual(sig, 'old_1_1')

    def test_a_failure_that_is_not_a_lost_instance_is_raised_without_resolving(self):
        fake = Fake([done(err='bad request', code=1)])
        out, _ = self.run_ctl(fake)
        self.assertIn('bad request', str(out))
        self.assertEqual(fake.count('hyprctl', 'instances'), 0)
        self.assertEqual(fake.count('hyprctl', 'monitors'), 1)
        self.assertFalse(host.verified)

    def test_a_dispatch_error_runs_once(self):
        guard.disarm()
        fake = Fake([done('invalid dispatcher')])
        out, _ = self.run_ctl(fake, 'old_1_1', 'dispatch', 'x')
        self.assertIn('invalid dispatcher', str(out))
        self.assertEqual(fake.count('hyprctl', 'dispatch'), 1)
        self.assertEqual(fake.count('hyprctl', 'instances'), 0)

    def test_a_dispatch_that_never_connected_is_retried(self):
        guard.disarm()
        fake = Fake([done(err=LOST, code=1), done('ok')])
        out, sig = self.run_ctl(fake, 'old_1_1', 'dispatch', 'x')
        self.assertEqual((out, sig), ('ok', LIVE))
        self.assertEqual(fake.count('hyprctl', 'dispatch'), 2)


class Grants(Base):
    def setUp(self):
        super().setUp()
        host.verified = False
        self.addCleanup(setattr, host, 'verified', False)
        layers = patch.object(control.host, 'layers', return_value=[])
        layers.start()
        self.addCleanup(layers.stop)

    def granted_under(self, sig):
        with patch.dict(os.environ, {SIG: sig}):
            return grant()

    def test_a_grant_and_a_request_carry_their_instance(self):
        self.assertEqual(self.granted_under('A')['instance'], 'A')
        with patch.dict(os.environ, {SIG: 'A'}):
            self.assertEqual(control.set_owner('agent', 'agent')['instance'], 'A')

    def test_a_grant_is_revoked_once_the_instance_changed(self):
        before = self.granted_under('A')
        host.verified = True
        with patch.dict(os.environ, {SIG: 'B'}):
            state = control.read_state()
        self.assertEqual(state['owner'], 'off')
        self.assertEqual(state['why'], control.RESTARTED)
        self.assertEqual(state['generation'], before['generation'] + 1)
        events = [json.loads(l)['event'] for l in (control.root() / 'audit.jsonl').read_text().splitlines()]
        self.assertIn('instance-changed-revoke', events)

    def test_a_process_that_has_not_reached_hyprland_does_not_revoke(self):
        self.granted_under('A')
        with patch.dict(os.environ, {SIG: 'B'}):
            self.assertEqual(control.read_state()['owner'], 'agent')

    def test_the_same_instance_is_kept(self):
        self.granted_under('A')
        host.verified = True
        with patch.dict(os.environ, {SIG: 'A'}):
            self.assertEqual(control.read_state()['owner'], 'agent')

    def test_a_grant_without_a_stamp_is_kept(self):
        state = self.granted_under('A')
        state.pop('instance')
        control._write(state)
        host.verified = True
        with patch.dict(os.environ, {SIG: 'B'}):
            self.assertEqual(control.read_state()['owner'], 'agent')

    def test_a_pending_request_is_revoked_too(self):
        with patch.dict(os.environ, {SIG: 'A'}):
            control.set_owner('agent', 'agent')
        host.verified = True
        with patch.dict(os.environ, {SIG: 'B'}):
            state = control.read_state()
        self.assertEqual((state['owner'], state['why']), ('off', control.RESTARTED))

    def test_the_switch_is_audited(self):
        # control wires host.on_switch at import; a reload of host must not lose it
        self.assertIsNotNone(host.on_switch)
        host.on_switch('A', 'B')
        last = json.loads((control.root() / 'audit.jsonl').read_text().splitlines()[-1])
        self.assertEqual((last['event'], last['from'], last['to']), ('instance-changed', 'A', 'B'))


class Doctor(Base):
    def test_resolved_is_reported(self):
        def find():
            os.environ[SIG] = 'new'
            return '0x1'
        with patch.dict(os.environ, {SIG: 'old'}), patch.object(api.host, 'focused_address', side_effect=find):
            report = api.doctor()
        self.assertEqual(report['resolved'], {'from': 'old', 'to': 'new'})

    def test_nothing_is_reported_when_nothing_changed(self):
        with patch.dict(os.environ, {SIG: 'old'}), patch.object(api.host, 'focused_address', return_value='0x1'):
            self.assertNotIn('resolved', api.doctor())

    def test_stale_is_reported_when_resolving_fails(self):
        with patch.dict(os.environ, {SIG: 'old'}), \
             patch.object(api.host, 'focused_address', side_effect=RuntimeError('Hyprland: gone')):
            report = api.doctor()
        self.assertFalse(report['ok'])
        self.assertEqual(report['stale'], 'old')
        self.assertIn('restart the MCP server', report['hint'])


class IndexSh(Base):
    def test_hyprctl_is_retried_after_a_lost_instance(self):
        fake = Fake([done(err=LOST, code=1), done('fine')])
        with patch.dict(os.environ, {SIG: 'old'}), patch.object(subprocess, 'run', fake):
            self.assertEqual(index.sh('hyprctl', 'binds', '-j'), 'fine')
            self.assertEqual(os.environ[SIG], LIVE)
        self.assertEqual(fake.count('hyprctl', 'binds'), 2)

    def test_other_commands_are_not(self):
        fake = Fake([done(err=LOST, code=1)])
        with patch.object(subprocess, 'run', fake):
            with self.assertRaises(RuntimeError):
                index.sh('ls')
        self.assertEqual(len(fake.calls), 1)


if __name__ == '__main__':
    unittest.main()
