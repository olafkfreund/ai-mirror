"""#40: a grant belongs to whoever was granted it, and only they may end it."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import control
from ai_mirror.control import MirrorError

from test_invariants import Base, grant


class Registration(Base):
    """register_server publishes an identity; unregister_server takes it back."""

    def tearDown(self):
        control.SERVER = None
        super().tearDown()

    def test_registering_sets_the_identity(self):
        control.register_server()
        self.addCleanup(control.unregister_server)
        self.assertEqual(control.SERVER['pid'], os.getpid())
        self.assertEqual(control.SERVER['start'], control.proc_start(os.getpid()))

    def test_unregistering_clears_it(self):
        control.register_server()
        control.unregister_server()
        self.assertIsNone(control.SERVER)


class Recording(Base):
    """The request carries who asked; the grant carries who holds it."""

    def tearDown(self):
        control.SERVER = None
        super().tearDown()

    def test_a_cli_grant_is_held_by_nobody(self):
        granted = grant()
        self.assertIsNone(granted['held_by'])
        self.assertIn('held_by', granted)  # null, not absent: a CLI caller holds it

    def test_a_server_grant_records_the_server(self):
        control.register_server()
        self.addCleanup(control.unregister_server)
        granted = grant()
        self.assertEqual(granted['held_by'], control.SERVER)

    def test_the_request_carries_it_before_the_answer(self):
        control.register_server()
        self.addCleanup(control.unregister_server)
        pending = control.set_owner('agent', 'agent')
        self.assertEqual(pending['request']['server'], control.SERVER)



class Releasing(Base):
    """Only the holder ends a grant -- and the person at the keyboard, always."""

    def tearDown(self):
        control.SERVER = None
        super().tearDown()

    def as_a_server(self):
        """This process's identity, without registering it.

        register_server also publishes a pid file, and releasing control
        SIGUSR1s every pid in that directory -- including this one, which ends
        the test run. The identity is what these tests are about; the signal is
        not.
        """
        control.SERVER = {'pid': os.getpid(), 'start': control.proc_start(os.getpid())}
        return control.SERVER

    def _grant_held_by(self, held_by):
        grant()
        state = control.read_state()
        if held_by is control.SERVER and held_by is None:
            state.pop('held_by', None)
        else:
            state['held_by'] = held_by
        control._write(state)
        return state

    def test_an_agent_may_end_its_own_grant(self):
        self.as_a_server()
        grant()
        self.assertEqual(control.set_owner('off', 'agent')['owner'], 'off')

    def test_an_agent_may_not_end_a_live_foreign_grant(self):
        self.as_a_server()
        # another process, demonstrably alive: this test's own parent
        self._grant_held_by({'pid': os.getppid(), 'start': control.proc_start(os.getppid())})
        with self.assertRaises(MirrorError) as caught:
            control.set_owner('off', 'agent')
        self.assertEqual(caught.exception.code, 'not_owner')
        self.assertIn('another agent', str(caught.exception))
        self.assertEqual(control.read_state()['owner'], 'agent')

    def test_an_agent_may_not_end_a_cli_grant(self):
        self.as_a_server()
        self._grant_held_by(None)
        with self.assertRaises(MirrorError):
            control.set_owner('off', 'agent')

    def test_a_grant_from_before_this_change_is_still_releasable(self):
        self.as_a_server()
        grant()
        state = control.read_state()
        del state['held_by']
        control._write(state)
        self.assertEqual(control.set_owner('off', 'agent')['owner'], 'off')

    def test_a_grant_whose_holder_is_gone_is_releasable(self):
        self.as_a_server()
        self._grant_held_by({'pid': 2 ** 22, 'start': '12345'})  # no such process
        self.assertEqual(control.set_owner('off', 'agent')['owner'], 'off')

    def test_a_reused_pid_does_not_count_as_the_holder(self):
        self.as_a_server()
        self._grant_held_by({'pid': os.getppid(), 'start': 'not-the-birth-time'})
        self.assertEqual(control.set_owner('off', 'agent')['owner'], 'off')

    def test_the_person_at_the_keyboard_is_never_refused(self):
        self.as_a_server()
        for held_by in ({'pid': os.getppid(), 'start': control.proc_start(os.getppid())}, None):
            self._grant_held_by(held_by)
            self.assertEqual(control.set_owner('off', 'human')['owner'], 'off')


if __name__ == '__main__':
    unittest.main()
