"""`launch` reports the window it opened (#54)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_mirror import api, guard

from test_invariants import Base, grant


class LaunchGuard(Base):
    def test_unstubbed_launch_is_blocked(self):
        grant()
        with self.assertRaises(guard.Blocked):
            api.run('launch', {'argv': ['true']}, by='agent')


if __name__ == '__main__':
    unittest.main()
