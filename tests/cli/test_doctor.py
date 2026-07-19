import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from macropad import cli, diagnostics
from macropad.cli import doctor, profile_files, service


class DoctorCommandTests(unittest.TestCase):
    def test_doctor_is_available_as_a_command(self):
        with patch('sys.argv', ['macropad', 'doctor']):
            args = cli.parse_args()

        self.assertEqual('doctor', args.subcommand)

    def test_main_dispatches_doctor(self):
        args = SimpleNamespace(subcommand='doctor')

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.doctor.run', return_value=1) as run_doctor,
        ):
            exit_status = cli.main()

        self.assertEqual(1, exit_status)
        run_doctor.assert_called_once_with()

    def test_doctor_renders_remediation_and_returns_failure(self):
        results = [
            diagnostics.DiagnosticResult(
                diagnostics.FAIL,
                'Input devices',
                'Permission denied.',
                'Join the input group.',
            ),
            diagnostics.DiagnosticResult(
                diagnostics.INFO,
                'Notifications',
                'Unavailable.',
            ),
        ]
        output = io.StringIO()

        with (
            patch('macropad.cli.doctor.diagnostics.run_checks', return_value=results) as run_checks,
            patch(
                'macropad.cli.doctor.service.get_info',
                return_value=service.ServiceInfo('/units/macropad.service', True),
            ),
            redirect_stdout(output),
        ):
            exit_status = doctor.run()

        self.assertEqual(1, exit_status)
        run_checks.assert_called_once_with(
            profile_files.DEFAULT_CONFIG_DIR,
            '/units/macropad.service',
            True,
            None,
            None,
        )
        self.assertEqual(
            'FAIL Input devices: Permission denied.\n'
            '  Fix: Join the input group.\n'
            'INFO Notifications: Unavailable.\n'
            '\n'
            'Doctor found 1 blocking issue(s).\n',
            output.getvalue(),
        )

    def test_doctor_returns_success_when_only_optional_checks_are_unavailable(self):
        results = [
            diagnostics.DiagnosticResult(diagnostics.PASS, 'Input devices', 'Ready.'),
            diagnostics.DiagnosticResult(
                diagnostics.WARN,
                'Macro Keyboard',
                'Grabbed by the active service.',
            ),
            diagnostics.DiagnosticResult(diagnostics.INFO, 'Notifications', 'Unavailable.'),
        ]

        with (
            patch('macropad.cli.doctor.diagnostics.run_checks', return_value=results),
            patch(
                'macropad.cli.doctor.service.get_info',
                return_value=service.ServiceInfo(None, False, 'not installed'),
            ),
            redirect_stdout(io.StringIO()),
        ):
            exit_status = doctor.run()

        self.assertEqual(0, exit_status)


if __name__ == '__main__':
    unittest.main()
