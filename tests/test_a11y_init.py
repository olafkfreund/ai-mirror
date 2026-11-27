"""A missing accessibility bus must not abort the CLI or MCP process."""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from test_invariants import Base
from ai_mirror import a11y, index
from ai_mirror.control import MirrorError


class FakeAtspi:
    def __init__(self):
        self.available = False
        self.initialized = False
        self.connected = False
        self.desktop_reads = 0
        self.exits = 0

    def init(self):
        # libatspi marks itself initialized even when connecting fails. A
        # second init then returns 1, although get_desktop would still abort.
        if self.initialized:
            return 1
        self.initialized = True
        self.connected = self.available
        return 0 if self.connected else 2

    def exit(self):
        self.exits += 1
        self.initialized = self.connected = False

    def get_desktop(self, _number):
        self.desktop_reads += 1
        if not self.connected:
            self.init()
        if not self.connected:
            raise AssertionError('get_desktop would call abort() without a bus')
        return SimpleNamespace(get_child_count=lambda: 0)


class AccessibilityInit(Base):
    def setUp(self):
        super().setUp()
        self.atspi = FakeAtspi()
        gi = ModuleType('gi')
        gi.require_version = lambda *_args: None
        gi.repository = ModuleType('gi.repository')
        gi.repository.Atspi = self.atspi
        modules = patch.dict(sys.modules, {'gi': gi, 'gi.repository': gi.repository})
        modules.start()
        self.addCleanup(modules.stop)

    def test_missing_bus_is_unavailable_before_reading_the_desktop(self):
        with self.assertRaises(MirrorError) as error:
            a11y.tree(enable=False)
        self.assertEqual(error.exception.code, 'unavailable')
        self.assertIn('accessibility bus', str(error.exception))
        self.assertEqual(self.atspi.desktop_reads, 0)
        self.assertEqual(self.bus_writes, [])

    def test_repeated_index_calls_keep_other_sections_without_enabling_a11y(self):
        for _ in range(2):
            result = index.build({'section': ['nav', 'gotchas']})
            self.assertIn('unavailable: accessibility bus', result['nav']['_unavailable'])
            self.assertIn('text', result['gotchas'])
        self.assertEqual(self.atspi.desktop_reads, 0)
        self.assertEqual(self.bus_writes, [])

    def test_a_failed_init_can_recover_when_the_bus_becomes_available(self):
        with self.assertRaises(MirrorError):
            a11y.tree(enable=False)
        self.atspi.available = True
        self.assertEqual(a11y.tree(enable=False)['nodes'], [])
        self.assertEqual(self.atspi.desktop_reads, 1)
        self.assertEqual(self.atspi.exits, 1)
        self.assertEqual(self.bus_writes, [])

    def test_success_and_already_initialized_do_not_close_the_connection(self):
        self.atspi.available = True
        for _ in range(2):
            self.assertEqual(a11y.tree(enable=False)['nodes'], [])
        self.assertEqual(self.atspi.desktop_reads, 2)
        self.assertEqual(self.atspi.exits, 0)
        self.assertEqual(self.bus_writes, [])

    def test_resolve_also_refuses_an_unavailable_bus(self):
        with self.assertRaises(MirrorError) as error:
            a11y.resolve('0')
        self.assertEqual(error.exception.code, 'unavailable')
        self.assertEqual(self.atspi.desktop_reads, 0)
