"""Exercise badge and restore with an isolated runtime directory and a fake desktop."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import cursor, guard


class CursorRestore(unittest.TestCase):
    def setUp(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        env = patch.dict(os.environ, XDG_RUNTIME_DIR=runtime.name, HYPRLAND_INSTANCE_SIGNATURE='test',
                         XCURSOR_THEME='default', XCURSOR_SIZE='24')
        env.start()
        self.addCleanup(env.stop)
        guard.arm()
        self.addCleanup(guard.disarm)
        self.configured = ['Bibata-Modern-Ice', 30]
        self.gtk = self.configured
        self.synced = True
        self.applied = []
        self.enterContext(patch.object(cursor, 'configured_cursor', lambda: (self.configured, self.synced)))
        self.settings = Mock()
        self.settings.get_string.side_effect = lambda _: self.gtk[0] if self.gtk else ''
        self.settings.get_int.side_effect = lambda _: self.gtk[1] if self.gtk else 0
        self.enterContext(patch.object(cursor, 'gtk_settings', return_value=self.settings))
        self.enterContext(patch.object(cursor, 'set_cursor', self.apply))

    def apply(self, value):
        self.applied.append(value)
        self.gtk = value  # Hyprland syncs setcursor into GSettings.

    def test_idle_start_and_repeated_release_leave_the_desktop_alone(self):
        cursor.sync(False)
        self.assertEqual(self.applied, [])
        cursor.sync(True)
        cursor.sync(False)
        cursor.sync(False)
        self.assertEqual(self.applied, [[cursor.BADGE, 30], self.configured])

    def test_shell_restart_during_grant_preserves_manual_theme_and_size(self):
        desktop = self.gtk = ['Human theme with spaces', 42]
        cursor.sync(True)
        cursor.sync(True)
        cursor.sync(False)
        self.assertEqual(self.applied, [[cursor.BADGE, 42], [cursor.BADGE, 42], desktop])

    def test_theme_switch_during_grant_wins(self):
        cursor.sync(True)
        self.configured = self.gtk = ['Bibata-Modern-Classic', 36]
        cursor.sync(False)
        self.assertEqual(self.applied[-1], self.configured)

    def test_restore_without_gsettings_uses_live_compositor(self):
        self.gtk = None
        cursor.sync(True)
        self.configured = ['Native theme', 40]
        self.gtk = None
        cursor.sync(False)
        self.assertEqual(self.applied[-1], self.configured)

    def test_failed_restore_can_be_retried_in_another_shell(self):
        cursor.sync(True)
        with patch.object(cursor, 'set_cursor', side_effect=RuntimeError('IPC failed')):
            with self.assertRaises(RuntimeError):
                cursor.sync(False)
        cursor.sync(False)
        self.assertEqual(self.applied[-1], self.configured)

    def test_a_second_compositor_does_not_restore_the_first_ones_badge(self):
        cursor.sync(True)
        with patch.dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE='other'):
            cursor.sync(False)
        self.assertEqual(self.applied, [[cursor.BADGE, 30]])

    def test_native_theme_and_gtk_fallback_have_separate_restore_targets(self):
        self.configured = ['Native theme', 40]
        self.synced = False
        gtk = self.gtk = ['GTK theme', 32]
        cursor.sync(True)
        self.assertEqual(self.applied[-1], [cursor.BADGE, 40])
        with patch.object(cursor, 'restore_gtk') as restore:
            cursor.sync(False)
            restore.assert_called_once_with(self.settings, gtk)
        self.assertEqual(self.applied[-1], self.configured)

class CompositorPreference(unittest.TestCase):
    def test_read_current_theme_with_spaces_as_data(self):
        with patch.object(cursor.subprocess, 'check_output', return_value='synced\n36\nMy Ice Theme\n') as call:
            self.assertEqual(cursor.configured_cursor(), (['My Ice Theme', 36], True))
            self.assertEqual(call.call_args.args[0], ['hyprctl', 'repl', cursor.PREFERENCE])

    def test_never_restore_the_agent_badge_as_a_preference(self):
        with patch.object(cursor.subprocess, 'check_output', return_value='configured\n0\nai-mirror-agent\n'):
            self.assertEqual(cursor.configured_cursor(), (['default', 24], False))
