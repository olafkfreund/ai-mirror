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
REAL_RUNNING = control._instance_running  # Base stubs it; the grant tests want the real one
REAL_IS_HYPRLAND = control._is_hyprland
NOT_SET = 'HYPRLAND_INSTANCE_SIGNATURE not set! (is hyprland running?)'  # hyprctl 0.56, verbatim
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
        self.addCleanup(setattr, host, 'on_switch', None)

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

    def test_an_unset_signature_is_found(self):
        fake = Fake([done(err=NOT_SET, code=1), done('[]')])
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

    def test_a_dispatch_error_runs_once(self):
        guard.disarm()
        fake = Fake([done('invalid dispatcher')])
        out, _ = self.run_ctl(fake, 'old_1_1', 'dispatch', 'x')
        self.assertIn('invalid dispatcher', str(out))
        self.assertEqual(fake.count('hyprctl', 'dispatch'), 1)
        self.assertEqual(fake.count('hyprctl', 'instances'), 0)

    def test_a_dispatch_is_not_sent_to_a_new_instance_under_an_old_grant(self):
        guard.disarm()
        fake = Fake([done(err=LOST, code=1), done('ok')])
        out, sig = self.run_ctl(fake, 'old_1_1', 'dispatch', 'x')
        self.assertIsInstance(out, RuntimeError)
        self.assertIn('not sent', str(out))
        self.assertEqual(fake.count('hyprctl', 'dispatch'), 1)
        self.assertEqual(sig, LIVE)  # the process still follows the live instance
        self.assertEqual(self.switches, [('old_1_1', LIVE)])

    def test_resolve_timeouts_are_the_callers(self):
        seen = []
        fake = Fake([done(err=LOST, code=1), done('[]')], systemd='')
        def spy(argv, **kw):
            seen.append(kw['timeout'])
            return fake(argv, **kw)
        with patch.object(subprocess, 'run', spy), patch.dict(os.environ, {SIG: 'old_1_1'}):
            host.ctl('monitors', timeout=2)
        self.assertEqual(seen, [2, 2, 2, 2])  # monitors, instances, systemctl, monitors


class Grants(Base):
    """The stamp is checked against whether that Hyprland is alive, never against our own env."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(control, '_instance_running', REAL_RUNNING)
        patcher.start()
        self.addCleanup(patcher.stop)
        named = patch.object(control, '_is_hyprland', return_value=True)  # our pid stands in for Hyprland
        self.is_hyprland = named.start()
        self.addCleanup(named.stop)
        layers = patch.object(control.host, 'layers', return_value=[])
        layers.start()
        self.addCleanup(layers.stop)
        dead = subprocess.Popen(['true'])
        dead.wait()
        self.dead_pid = dead.pid

    def lock(self, sig, pid=None):
        path = Path(os.environ['XDG_RUNTIME_DIR']) / 'hypr' / sig
        path.mkdir(parents=True, exist_ok=True)
        (path / 'hyprland.lock').write_text(f'{os.getpid() if pid is None else pid}\nwayland-1\n')

    def granted_under(self, sig):
        self.lock(sig)
        with patch.dict(os.environ, {SIG: sig}):
            return grant()

    def test_a_grant_and_a_request_carry_their_instance(self):
        self.assertEqual(self.granted_under('A')['instance'], 'A')
        with patch.dict(os.environ, {SIG: 'A'}):
            self.assertEqual(control.set_owner('agent', 'agent')['instance'], 'A')

    def test_a_request_from_a_stale_environment_is_not_stamped_with_it(self):
        with patch.dict(os.environ, {SIG: 'gone'}):  # no lock file: not running
            pending = control.set_owner('agent', 'agent')
            self.assertNotIn('instance', pending)
            self.assertEqual(control.read_state()['owner'], 'pending')

    def test_a_grant_is_revoked_when_its_instance_died_even_if_our_env_still_names_it(self):
        # A long-running server: env A, grant stamped A, Hyprland A has since died.
        before = self.granted_under('A')
        (Path(os.environ['XDG_RUNTIME_DIR']) / 'hypr/A/hyprland.lock').write_text(f'{self.dead_pid}\n')
        with patch.dict(os.environ, {SIG: 'A'}):
            state = control.read_state()
        self.assertEqual(state['owner'], 'off')
        self.assertEqual(state['why'], control.RESTARTED)
        self.assertEqual(state['generation'], before['generation'] + 1)
        events = [json.loads(l)['event'] for l in (control.root() / 'audit.jsonl').read_text().splitlines()]
        self.assertIn('instance-changed-revoke', events)

    def test_a_reused_pid_that_is_not_hyprland_counts_as_not_running(self):
        self.granted_under('A')  # the lock names this test process, which is alive but is python
        with patch.object(control, '_is_hyprland', wraps=REAL_IS_HYPRLAND), patch.dict(os.environ, {SIG: 'A'}):
            self.assertEqual(control.read_state()['owner'], 'off')

    def test_a_pid_we_cannot_signal_is_not_our_hyprland(self):
        self.lock('A')
        with patch.object(os, 'kill', side_effect=PermissionError):
            self.assertFalse(control._instance_running('A'))

    def test_a_missing_runtime_dir_falls_back_to_run_user(self):
        runtime = os.environ['XDG_RUNTIME_DIR']
        self.lock('A')
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': ''}), \
             patch.object(os, 'getuid', return_value=0), \
             patch.object(control, 'Path', side_effect=lambda p: Path(runtime) if p == '/run/user/0' else Path(p)):
            self.assertTrue(control._instance_running('A'))

    def test_a_grant_is_refused_when_its_hyprland_is_not_running(self):
        with patch.dict(os.environ, {SIG: 'gone'}):  # no lock file
            with self.assertRaises(control.MirrorError):
                grant()
        self.assertNotEqual(control.read_state().get('owner'), 'agent')
        # #85: the trail must not claim a grant that did not happen
        events = [one['event'] for one in control.read_audit(0)['entries']]
        self.assertNotIn('confirmed', events)

    def test_a_missing_lock_file_counts_as_not_running(self):
        self.granted_under('A')
        (Path(os.environ['XDG_RUNTIME_DIR']) / 'hypr/A/hyprland.lock').unlink()
        self.assertEqual(control.read_state()['owner'], 'off')

    def test_a_fresh_grant_survives_a_server_that_still_has_the_old_env(self):
        # Stamped B by the answering CLI; this process still says A, and A is dead.
        self.lock('B')
        granted = self.granted_under('B')
        with patch.dict(os.environ, {SIG: 'A'}):
            state = control.read_state()
        self.assertEqual((state['owner'], state['generation']), ('agent', granted['generation']))

    def test_a_live_instance_is_kept(self):
        self.granted_under('A')
        self.assertEqual(control.read_state()['owner'], 'agent')

    def test_a_grant_without_a_stamp_is_kept(self):
        state = self.granted_under('A')
        state.pop('instance')
        control._write(state)
        self.assertEqual(control.read_state()['owner'], 'agent')

    def test_a_pending_request_is_revoked_too(self):
        self.lock('A')
        with patch.dict(os.environ, {SIG: 'A'}):
            control.set_owner('agent', 'agent')
        (Path(os.environ['XDG_RUNTIME_DIR']) / 'hypr/A/hyprland.lock').write_text(f'{self.dead_pid}\n')
        state = control.read_state()
        self.assertEqual((state['owner'], state['why']), ('off', control.RESTARTED))

    def test_a_switch_audits_stops_the_helper_and_revokes(self):
        self.granted_under('A')
        (Path(os.environ['XDG_RUNTIME_DIR']) / 'hypr/A/hyprland.lock').write_text(f'{self.dead_pid}\n')
        with patch.object(control.HELPER, 'stop') as stop:
            host.on_switch('A', 'B')  # what resolve() calls
        stop.assert_called_once_with()
        self.assertEqual(control._load()['why'], control.RESTARTED)  # raw file: the hook did it, not a later read
        last = [json.loads(l) for l in (control.root() / 'audit.jsonl').read_text().splitlines()]
        self.assertIn(('instance-changed', 'A', 'B'),
                      [(e['event'], e.get('from'), e.get('to')) for e in last])


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
             patch.object(api.host, 'focused_address', side_effect=RuntimeError('Hyprland: ' + LOST)):
            report = api.doctor()
        self.assertFalse(report['ok'])
        self.assertEqual(report['stale'], 'old')
        self.assertIn('restart the MCP server', report['hint'])

    def test_no_restart_hint_when_the_failure_was_something_else(self):
        for why in ('Hyprland: Hyprland is not running for this user (hyprctl instances is empty)',
                    'Hyprland: 2 Hyprland instances are running (a, b); set X'):
            with patch.dict(os.environ, {SIG: 'old'}), \
                 patch.object(api.host, 'focused_address', side_effect=RuntimeError(why)):
                report = api.doctor()
            self.assertNotIn('stale', report)
            self.assertNotIn('restart the MCP server', report.get('hint', ''))


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
