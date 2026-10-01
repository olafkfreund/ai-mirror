"""The confirm dialog's QML wiring (#48), checked as text.

The dialog imports Omarchy shell modules, so it cannot be loaded in a test.
These are the lines whose loss would quietly reopen #48's holes: a request
that inherits the previous one's second, and a click that grants without the
pointer having moved. The rule itself is tested in test_confirm_keys.mjs.
"""
from pathlib import Path
import re
import unittest

QML = (Path(__file__).resolve().parents[1] / 'plugin' / 'AgentConfirmDialog.qml').read_text()


def request_handler():
    """onRequestChanged, up to the window it guards."""
    return QML[QML.index('onRequestChanged:'):QML.index('PanelWindow {')]


class ConfirmWiring(unittest.TestCase):
    def test_every_new_request_gets_its_own_second(self):
        body = request_handler()
        new_id = body[body.index('request.id !== armedFor'):]
        self.assertIn('ready = false', new_id)
        self.assertIn('grace.restart()', new_id)

    def test_a_vanished_request_starts_over(self):
        body = request_handler()
        gone = body[:body.index('request.id !== armedFor')]
        for line in ('armedFor = ""', 'ready = false', 'grace.stop()'):
            self.assertIn(line, gone)

    def test_allow_click_needs_pointer_movement_and_nothing_else(self):
        self.assertIn('onClicked: if (root.pointerArmed) root.answer("confirm", "dialog-click")', QML)
        self.assertEqual(QML.count('root.answer("confirm"'), 1)

    def test_every_answer_says_how_it_was_given(self):
        calls = re.findall(r'root\.answer\(.*', QML)
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertRegex(call, r'root\.answer\([^,]+, "dialog-')

    def test_keys_go_through_the_tested_rule(self):
        self.assertIn('ConfirmKeys.decide({ ready: root.ready }', QML)


if __name__ == '__main__':
    unittest.main()
