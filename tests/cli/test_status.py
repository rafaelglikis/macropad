import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from macropad import cli, runtime_status
from macropad.cli import service, status


class RuntimeStatusCommandTests(unittest.TestCase):
    def test_status_renders_workers_configuration_error_and_retry(self):
        snapshot = {
            'pid': 1234,
            'configuration_error': 'bindings.KEY_A.up conflicts',
            'workers': [
                {
                    'device': 'Macro Keyboard',
                    'profiles': ['/profiles/macro.yml'],
                    'state': 'listening',
                    'pid': 1235,
                    'paths': ['/dev/input/event12'],
                    'error': None,
                    'retry_seconds': None,
                },
                {
                    'device': 'Media Pad',
                    'profiles': ['/profiles/media.yml'],
                    'state': 'backing_off',
                    'pid': None,
                    'paths': [],
                    'error': 'permission denied',
                    'retry_seconds': 3.25,
                },
            ],
        }
        output = io.StringIO()

        with (
            patch('macropad.cli.status.runtime_status.request_status', return_value=snapshot),
            redirect_stdout(output),
        ):
            exit_status = status.run()

        self.assertEqual(0, exit_status)
        self.assertIn('Macropad parent PID: 1234', output.getvalue())
        self.assertIn('Configuration: INVALID candidate retained', output.getvalue())
        self.assertIn('state: listening', output.getvalue())
        self.assertIn('paths: /dev/input/event12', output.getvalue())
        self.assertIn('state: backing_off (retry in 3.2s)', output.getvalue())
        self.assertIn('error: permission denied', output.getvalue())

    def test_unavailable_runtime_points_to_active_service_status(self):
        output = io.StringIO()

        with (
            patch(
                'macropad.cli.status.runtime_status.request_status',
                side_effect=runtime_status.RuntimeStatusUnavailable('missing socket'),
            ),
            patch(
                'macropad.cli.status.service.get_info',
                return_value=service.ServiceInfo('/units/macropad.service', True),
            ),
            redirect_stdout(output),
        ):
            exit_status = status.run()

        self.assertEqual(1, exit_status)
        self.assertIn('Runtime status unavailable', output.getvalue())
        self.assertIn('macropad service status', output.getvalue())

    def test_status_command_parses_and_dispatches(self):
        with patch('sys.argv', ['macropad', 'status']):
            args = cli.parse_args()

        self.assertEqual('status', args.subcommand)
        with (
            patch('macropad.cli.parse_args', return_value=SimpleNamespace(subcommand='status')),
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.status.run', return_value=7) as run_status,
        ):
            exit_status = cli.main()

        self.assertEqual(7, exit_status)
        run_status.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
