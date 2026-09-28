import unittest


class Red(unittest.TestCase):
    def test_red(self):
        self.fail('CI must go red on a failing test')
