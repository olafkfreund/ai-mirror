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


if __name__ == '__main__':
    unittest.main()
