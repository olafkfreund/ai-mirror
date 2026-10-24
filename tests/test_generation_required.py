import unittest
from unittest.mock import patch

from ai_mirror import a11y, api, control, host
from test_invariants import Base, grant

OPS = {'window': {'action': 'focus', 'address': '0x1'}, 'launch': {'argv': ['foot']},
       'a11y_act': {'node': '1.0', 'action': 'click'}, 'clipboard': {'action': 'write', 'text': 'x'}}


class GenerationRequired(Base):
    def test_missing_generation_names_the_sources(self):
        grant()
        for op, args in OPS.items():
            with self.assertRaisesRegex(ValueError, 'status, windows, a11y_find, a11y_tree'):
                api.run(op, args, by='agent')

    def test_stale_generation_is_refused(self):
        gen = grant()['generation']
        for op, args in OPS.items():
            with self.assertRaises(control.MirrorError) as cm:
                api.run(op, {**args, 'generation': gen + 1}, by='agent')
            self.assertEqual(cm.exception.code, 'stale_generation')

    def test_observations_carry_the_generation_read_before_the_walk(self):
        gen = grant()['generation']

        def bump(*a, **k):
            control.set_owner('off', 'human')
            return {'nodes': []}

        with patch.object(a11y, 'tree', bump):
            self.assertEqual(api.run('a11y_tree', {}, by='agent')['generation'], gen)
        gen = control.read_state()['generation']
        with patch.object(a11y, 'find', bump):
            self.assertEqual(api.run('a11y_find', {}, by='agent')['generation'], gen)
        gen = control.read_state()['generation']
        with patch.object(host, 'windows', lambda *a, **k: control.set_owner('agent', 'human') and []), \
                patch.object(host, 'layers', lambda: []):
            self.assertEqual(api.run('windows', {}, by='agent')['generation'], gen)


if __name__ == '__main__':
    unittest.main()
