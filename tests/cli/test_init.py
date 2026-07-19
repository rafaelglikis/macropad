import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from macropad import cli, diagnostics, interceptor, profiles
from macropad.cli import init as init_command
from macropad.cli import profile_files, service


class GuidedInitializationTests(unittest.TestCase):
    def setUp(self):
        self.input_ready = [
            diagnostics.DiagnosticResult(
                diagnostics.PASS,
                'Input devices',
                'Input access is ready.',
            )
        ]
        self.service_info = service.ServiceInfo(None, False, 'not installed')
        self.detected = interceptor.DetectedInput(
            'Macro Keyboard',
            'KEY_A',
            '/dev/input/event12',
        )

    def test_success_writes_and_validates_profile_in_resolved_directory(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'config' / 'macropad' / 'profiles'
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch('builtins.input', side_effect=['', 'echo ready']),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            profile_path = profile_directory / 'macro_keyboard_key_a.yml'
            loaded_profile = profiles.load_yml(str(profile_path))
            prepared_profiles = profiles.prepare_profiles([str(profile_path)])

        self.assertEqual(0, exit_status)
        self.assertEqual('Macro Keyboard', loaded_profile.device)
        self.assertEqual(('echo ready',), loaded_profile.keyboard.bindings['KEY_A'].actions['up'])
        self.assertEqual(1, len(prepared_profiles))
        self.assertIn(f'Created and validated {profile_path}', output.getvalue())
        self.assertIn('systemd service is not active', output.getvalue())
        self.assertIn('Next foreground command: macropad listen', output.getvalue())

    def test_keyboard_interrupt_leaves_no_profile(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch('builtins.input', side_effect=['', KeyboardInterrupt]),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            profile_paths = (
                list(profile_directory.glob('*.yml')) if profile_directory.exists() else []
            )

        self.assertEqual(130, exit_status)
        self.assertEqual([], profile_paths)
        self.assertIn('No partial profile was left behind.', output.getvalue())

    def test_success_refreshes_and_qualifies_active_service_state(self):
        active_service = service.ServiceInfo('/units/macropad.service', True)
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch(
                    'macropad.cli.init.service.get_info',
                    side_effect=[self.service_info, active_service],
                ) as get_service_info,
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch('builtins.input', side_effect=['', 'echo ready']),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

        self.assertEqual(0, exit_status)
        self.assertEqual(2, get_service_info.call_count)
        self.assertIn('active state alone cannot confirm watch mode', output.getvalue())
        self.assertIn('standard listen --watch command', output.getvalue())

    def test_detection_timeout_reports_retry_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch(
                    'macropad.cli.init.interceptor.detect',
                    side_effect=TimeoutError('No device was detected.'),
                ),
                patch('builtins.input', return_value=''),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            profile_paths = (
                list(profile_directory.glob('*.yml')) if profile_directory.exists() else []
            )

        self.assertEqual(1, exit_status)
        self.assertEqual([], profile_paths)
        self.assertIn('Initialization timed out: No device was detected.', output.getvalue())
        self.assertIn('Run macropad init to try again.', output.getvalue())

    def test_filename_collision_creates_numbered_fragment_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            profile_directory.mkdir()
            existing_path = profile_directory / 'macro_keyboard_key_a.yml'
            existing_content = (
                "device: Other Keyboard\nversion: '1'\nbindings:\n  KEY_B: echo existing\n"
            )
            existing_path.write_text(existing_content, encoding='utf-8')

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch('builtins.input', side_effect=['', 'echo new']),
                redirect_stdout(io.StringIO()),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            created_path = profile_directory / 'macro_keyboard_key_a_2.yml'

            self.assertEqual(0, exit_status)
            self.assertEqual(existing_content, existing_path.read_text(encoding='utf-8'))
            self.assertTrue(created_path.exists())

    def test_existing_device_lists_fragments_and_recaptures_bound_key(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            profile_directory.mkdir()
            existing_path = profile_directory / 'existing.yml'
            existing_path.write_text(
                "device: Macro Keyboard\nversion: '1'\nbindings:\n  KEY_A: echo existing\n",
                encoding='utf-8',
            )
            replacement = interceptor.DetectedInput(
                'Macro Keyboard',
                'KEY_B',
                '/dev/input/event12',
            )
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch(
                    'macropad.cli.init.interceptor.capture_key',
                    return_value=replacement,
                ) as capture_key,
                patch('builtins.input', side_effect=['', '', '', 'echo replacement']),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            created_path = profile_directory / 'macro_keyboard_key_b.yml'
            created_profile = profiles.load_yml(str(created_path))

        self.assertEqual(0, exit_status)
        capture_key.assert_called_once_with('Macro Keyboard', 10.0)
        self.assertIn(str(existing_path), output.getvalue())
        self.assertIn('KEY_A already has a release binding', output.getvalue())
        self.assertEqual(
            ('echo replacement',),
            created_profile.keyboard.bindings['KEY_B'].actions['up'],
        )

    def test_post_write_validation_failure_removes_generated_file(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'
            output = io.StringIO()

            with (
                patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
                patch(
                    'macropad.cli.init.diagnostics.check_input_devices',
                    return_value=self.input_ready,
                ),
                patch('macropad.cli.init.service.get_info', return_value=self.service_info),
                patch('macropad.cli.init.interceptor.detect', return_value=self.detected),
                patch('macropad.cli.init.validation.run', return_value=1),
                patch('builtins.input', side_effect=['', 'echo invalid']),
                redirect_stdout(output),
            ):
                exit_status = init_command.run(SimpleNamespace(timeout=10.0))

            profile_paths = list(profile_directory.glob('*.yml'))

        self.assertEqual(1, exit_status)
        self.assertEqual([], profile_paths)
        self.assertIn('generated profile failed validation', output.getvalue())
        self.assertIn('No partial profile was left behind.', output.getvalue())


class InitCommandDispatchTests(unittest.TestCase):
    def test_init_timeout_argument_and_dispatch(self):
        with patch('sys.argv', ['macropad', 'init', '--timeout', '15']):
            args = cli.parse_args()

        self.assertEqual('init', args.subcommand)
        self.assertEqual(15.0, args.timeout)

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.init.run', return_value=7) as run_init,
        ):
            exit_status = cli.main()

        self.assertEqual(7, exit_status)
        run_init.assert_called_once_with(args)

    def test_init_rejects_invalid_timeouts(self):
        for timeout in ('0', 'nan', 'inf'):
            with self.subTest(timeout=timeout):
                with (
                    patch('sys.argv', ['macropad', 'init', '--timeout', timeout]),
                    self.assertRaises(SystemExit),
                ):
                    cli.parse_args()


if __name__ == '__main__':
    unittest.main()
