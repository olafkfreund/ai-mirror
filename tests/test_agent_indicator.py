"""The agent indicator (#78): cursor badge and frame, checked as text.

Both follow state.json and are display only. What matters here is what would
quietly break the gate: a frame that unmaps when idle maps at the grant, is
new to _refuse_new_surfaces, and refuses all typing.
"""
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
CURSOR = ROOT / 'cursor'
QML = (ROOT / 'plugin' / 'Overlay.qml').read_text()


class AgentIndicator(unittest.TestCase):
    def test_cursor_switch_is_fixed_argv_and_not_a_dispatch(self):
        self.assertIn('"hyprctl", "setcursor"', QML)
        self.assertIn('"ai-mirror-agent"', QML)
        self.assertNotIn('dispatch', QML)

    def test_every_shell_start_applies_once(self):
        self.assertIn('Component.onCompleted: applyCursor()', QML)
        self.assertIn('appliedCursor: ""', QML)

    def test_frame_stays_mapped_for_the_input_gate(self):
        frame = QML[QML.index('Variants {'):]
        for line in ('mask: Region {}', 'WlrKeyboardFocus.None', 'WlrLayer.Top',
                     'border.width: root.agent ? 4 : 0'):
            self.assertIn(line, frame)
        self.assertNotIn('visible:', frame)

    def test_cursor_configs_point_at_images_that_hold_the_hotspot(self):
        cfgs = sorted(CURSOR.glob('*.cfg'))
        self.assertEqual(len(cfgs), 3)
        for cfg in cfgs:
            lines = cfg.read_text().splitlines()
            self.assertEqual(len(lines), 1, cfg)
            size, x, y, name = lines[0].split()
            self.assertEqual(size, '24')
            data = (CURSOR / name).read_bytes()
            w, h = struct.unpack('>II', data[16:24])
            self.assertLessEqual(w, 64)
            self.assertLessEqual(h, 40)
            self.assertLess(int(x), w)
            self.assertLess(int(y), h)

    def test_cursor_dir_has_no_symlinks(self):
        self.assertEqual([p for p in CURSOR.rglob('*') if p.is_symlink()], [])


if __name__ == '__main__':
    unittest.main()
