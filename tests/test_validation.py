import io
import unittest
from unittest.mock import patch

from macropad import validation
from macropad.config import ProfileValidationError


class ProfileValidationTests(unittest.TestCase):
    def test_complete_profile_set_prints_pass_sections_and_summary(self):
        profile_paths = ['/profiles/first.yml', '/profiles/second.yml']
        profile_configs = [object(), object()]
        output = io.StringIO()

        with (
            patch('macropad.validation.profiles.load_yml', side_effect=profile_configs),
            patch(
                'macropad.validation.profiles.prepare_loaded_profiles',
                return_value=[object(), object()],
            ) as prepare,
        ):
            exit_status = validation.run(profile_paths, stdout=output)

        self.assertEqual(0, exit_status)
        prepare.assert_called_once_with(list(zip(profile_paths, profile_configs, strict=True)))
        self.assertEqual(
            '/profiles/first.yml\n'
            '  PASS\n'
            '\n'
            '/profiles/second.yml\n'
            '  PASS\n'
            '\n'
            'Validated 2 profile files for 2 devices.\n',
            output.getvalue(),
        )

    def test_each_file_is_reported_and_multiline_errors_are_preserved(self):
        profile_paths = [
            '/profiles/first.yml',
            '/profiles/broken.yml',
            '/profiles/third.yml',
        ]
        validation_error = ProfileValidationError(
            '/profiles/broken.yml',
            '',
            'invalid YAML: while constructing a mapping\n'
            '  in "broken.yml", line 96, column 9\n'
            "found duplicate key 'hold'\n"
            '  in "broken.yml", line 99, column 9',
        )
        output = io.StringIO()

        with (
            patch(
                'macropad.validation.profiles.load_yml',
                side_effect=[object(), validation_error, object()],
            ),
            patch('macropad.validation.profiles.prepare_loaded_profiles') as prepare,
        ):
            exit_status = validation.run(profile_paths, stderr=output)

        self.assertEqual(1, exit_status)
        prepare.assert_not_called()
        self.assertEqual(
            '/profiles/first.yml\n'
            '  PARSED\n'
            '\n'
            '/profiles/broken.yml\n'
            '  FAIL\n'
            '  invalid YAML: while constructing a mapping\n'
            '    in "broken.yml", line 96, column 9\n'
            "  found duplicate key 'hold'\n"
            '    in "broken.yml", line 99, column 9\n'
            '\n'
            '/profiles/third.yml\n'
            '  PARSED\n'
            '\n'
            'Validation failed: 1 of 3 profile files has errors.\n'
            'Files marked PARSED passed standalone validation; '
            'merged validation did not complete.\n',
            output.getvalue(),
        )

    def test_merge_error_is_attributed_to_its_source_file(self):
        profile_paths = ['/profiles/first.yml', '/profiles/second.yml']
        validation_error = ProfileValidationError(
            '/profiles/second.yml',
            'bindings.KEY_A.up',
            'conflicts with an earlier profile fragment',
        )
        output = io.StringIO()

        with (
            patch('macropad.validation.profiles.load_yml', side_effect=[object(), object()]),
            patch(
                'macropad.validation.profiles.prepare_loaded_profiles',
                side_effect=validation_error,
            ),
        ):
            exit_status = validation.run(profile_paths, stderr=output)

        self.assertEqual(1, exit_status)
        self.assertIn('/profiles/first.yml\n  PARSED', output.getvalue())
        self.assertIn('/profiles/second.yml\n  FAIL', output.getvalue())
        self.assertIn(
            '  bindings.KEY_A.up: conflicts with an earlier profile fragment',
            output.getvalue(),
        )
        self.assertNotIn('profiles=(', output.getvalue())
        self.assertIn('merged validation did not complete', output.getvalue())

    def test_device_wide_error_is_reported_as_profile_set_failure(self):
        profile_paths = ['/profiles/layers.yml', '/profiles/more-layers.yml']
        validation_error = ProfileValidationError(
            "device 'Macro Keyboard'",
            'bindings',
            'expected at least one reachable base action',
        )
        output = io.StringIO()

        with (
            patch('macropad.validation.profiles.load_yml', side_effect=[object(), object()]),
            patch(
                'macropad.validation.profiles.prepare_loaded_profiles',
                side_effect=validation_error,
            ),
        ):
            exit_status = validation.run(profile_paths, stderr=output)

        self.assertEqual(1, exit_status)
        self.assertIn('/profiles/layers.yml\n  PARSED', output.getvalue())
        self.assertIn('/profiles/more-layers.yml\n  PARSED', output.getvalue())
        self.assertIn(
            "Profile set\n  FAIL\n  device 'Macro Keyboard': bindings: "
            'expected at least one reachable base action',
            output.getvalue(),
        )


if __name__ == '__main__':
    unittest.main()
