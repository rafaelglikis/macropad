import unittest
from types import SimpleNamespace

import yaml

import profile


class ProfileTests(unittest.TestCase):
    def test_generated_profile_can_be_serialized(self):
        generated_profile = profile.create_sample(SimpleNamespace(name='Demo Device'))

        profile_data = yaml.safe_load(generated_profile.dump())

        self.assertEqual('Demo Device', profile_data['device'])
        self.assertEqual('1', profile_data['version'])
        self.assertEqual(
            {
                'KEY_UP': {
                    'up': ["notify-send Hey! 'Hello from macropad!'"]
                }
            },
            profile_data['bindings'],
        )


if __name__ == '__main__':
    unittest.main()
