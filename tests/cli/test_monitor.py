import errno
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from evdev import ecodes

from macropad import cli, interceptor
from macropad.cli import monitor, service


class MonitorCommandTests(unittest.TestCase):
    def test_configured_device_names_ignores_invalid_profiles(self):
        with TemporaryDirectory() as directory:
            profile_directory = Path(directory)
            (profile_directory / 'valid.yml').write_text(
                "device: Macro Keyboard\nbindings:\n  KEY_A: 'true'\n",
                encoding='utf-8',
            )
            (profile_directory / 'invalid.yml').write_text('invalid: true\n', encoding='utf-8')

            with patch.object(monitor.profile_files, 'DEFAULT_CONFIG_DIR', profile_directory):
                device_names = monitor._configured_device_names()

        self.assertEqual({'Macro Keyboard'}, device_names)

    def test_key_aliases_keep_a_copyable_primary_name(self):
        with patch.object(
            monitor.ecodes,
            'KEY',
            {152: ['KEY_COFFEE', 'KEY_SCREENLOCK']},
        ):
            key_name = monitor._key_name(152)

        self.assertEqual('KEY_COFFEE (alias: KEY_SCREENLOCK)', key_name)

    def test_monitor_arguments_support_listing_and_exact_device_name(self):
        with patch('sys.argv', ['macropad', 'monitor']):
            list_args = cli.parse_args()
        with patch('sys.argv', ['macropad', 'monitor', 'Macro Keyboard']):
            monitor_args = cli.parse_args()

        self.assertEqual('monitor', list_args.subcommand)
        self.assertIsNone(list_args.device)
        self.assertEqual('Macro Keyboard', monitor_args.device)

    def test_main_dispatches_monitor(self):
        args = SimpleNamespace(subcommand='monitor', device=None)

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.monitor.run', return_value=0) as run_monitor,
        ):
            exit_status = cli.main()

        self.assertEqual(0, exit_status)
        run_monitor.assert_called_once_with(args)

    def test_listing_groups_name_collisions_and_reports_permission_failures(self):
        probes = [
            interceptor.DeviceAccessProbe('/dev/input/event1', 'Macro Keyboard'),
            interceptor.DeviceAccessProbe('/dev/input/event2', 'Macro Keyboard'),
            interceptor.DeviceAccessProbe('/dev/input/event3', 'Other Keyboard'),
            interceptor.DeviceAccessProbe(
                '/dev/input/event4',
                operation='open',
                error_number=errno.EACCES,
                error='permission denied',
            ),
        ]
        output = io.StringIO()

        with (
            patch('macropad.cli.monitor.interceptor.probe_device_access', return_value=probes),
            patch(
                'macropad.cli.monitor._configured_device_names',
                return_value={'Macro Keyboard'},
            ),
            redirect_stdout(output),
        ):
            exit_status = monitor.list_devices()

        self.assertEqual(0, exit_status)
        self.assertIn('Macro Keyboard [configured] (2 event paths)', output.getvalue())
        self.assertIn('  /dev/input/event1', output.getvalue())
        self.assertIn('Other Keyboard (1 event path)', output.getvalue())
        self.assertIn('UNREADABLE /dev/input/event4: permission denied', output.getvalue())

    def test_stream_renders_key_events_and_connection_status(self):
        args = SimpleNamespace(device='Macro Keyboard')
        event = SimpleNamespace(type=ecodes.EV_KEY, code=ecodes.KEY_A, value=1)
        output = io.StringIO()

        def stream(device_name, event_callback, status_callback, shutdown_requested):
            self.assertEqual('Macro Keyboard', device_name)
            status_callback('connected', '/dev/input/event1')
            event_callback('/dev/input/event1', event)
            shutdown_requested.set()

        with (
            patch('macropad.cli.monitor.signal.signal'),
            patch(
                'macropad.cli.monitor.service.get_info',
                return_value=service.ServiceInfo('/units/macropad.service', False),
            ),
            patch('macropad.cli.monitor.interceptor.monitor', side_effect=stream),
            redirect_stdout(output),
        ):
            exit_status = monitor.run(args)

        self.assertEqual(0, exit_status)
        self.assertIn("Waiting for input device 'Macro Keyboard'", output.getvalue())
        self.assertIn('CONNECTED', output.getvalue())
        self.assertIn('down', output.getvalue())
        self.assertIn('KEY_A', output.getvalue())
        self.assertIn('/dev/input/event1', output.getvalue())

    def test_stream_warns_when_service_is_active(self):
        args = SimpleNamespace(device='Macro Keyboard')
        output = io.StringIO()

        with (
            patch('macropad.cli.monitor.signal.signal'),
            patch(
                'macropad.cli.monitor.service.get_info',
                return_value=service.ServiceInfo('/units/macropad.service', True),
            ),
            patch('macropad.cli.monitor.interceptor.monitor'),
            redirect_stdout(output),
        ):
            monitor.run(args)

        self.assertIn('service is active', output.getvalue())
        self.assertIn('stop it if this device produces no events', output.getvalue())


if __name__ == '__main__':
    unittest.main()
