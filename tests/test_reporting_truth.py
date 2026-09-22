"""#30: a result a caller cannot check must not be wrong in the reassuring direction."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror.control import MirrorError


class Details(unittest.TestCase):
    """MirrorError carries the facts its message states in prose."""

    def test_details_are_kept(self):
        error = MirrorError('wrong_target', 'partial', {'delivered': 9, 'of': 14})
        self.assertEqual(error.details, {'delivered': 9, 'of': 14})

    def test_two_argument_calls_still_work(self):
        error = MirrorError('unavailable', 'no helper')
        self.assertEqual(error.details, {})
        self.assertEqual(str(error), 'unavailable: no helper')


if __name__ == '__main__':
    unittest.main()
