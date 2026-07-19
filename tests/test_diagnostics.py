import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macropad import diagnostics, interceptor


class InputDiagnosticTests(unittest.TestCase):
    def test_input_failures_are_classified_with_remediation(self):
        probes = [
            interceptor.DeviceAccessProbe('/dev/input/event1', 'Readable Keyboard'),
            interceptor.DeviceAccessProbe(
                '/dev/input/event2',
                operation='open',
                error_number=errno.EACCES,
                error='permission denied',
            ),
            interceptor.DeviceAccessProbe(
                '/dev/input/event3',
                'Busy Keyboard',
                operation='grab',
                error_number=errno.EBUSY,
                error='device busy',
            ),
            interceptor.DeviceAccessProbe(
                '/dev/input/event4',
                operation='open',
                error_number=errno.ENODEV,
                error='device lost',
            ),
        ]

        with patch('macropad.diagnostics.interceptor.probe_device_access', return_value=probes):
            results = diagnostics.check_input_devices(service_active=False)

        self.assertEqual(
            [diagnostics.PASS, diagnostics.FAIL, diagnostics.FAIL, diagnostics.INFO],
            [result.status for result in results],
        )
        self.assertIn('Permission denied', results[1].message)
        self.assertIn('every keystroke', results[1].remediation)
        self.assertIn('exclusively grabbed', results[2].message)

    def test_missing_input_devices_is_blocking(self):
        with patch('macropad.diagnostics.interceptor.probe_device_access', return_value=[]):
            results = diagnostics.check_input_devices(service_active=False)

        self.assertEqual(1, len(results))
        self.assertTrue(results[0].blocking)

    def test_active_service_grab_conflict_is_a_nonblocking_warning(self):
        probes = [
            interceptor.DeviceAccessProbe(
                '/dev/input/event1',
                'Macro Keyboard',
                operation='grab',
                error_number=errno.EBUSY,
                error='device busy',
            )
        ]

        with patch('macropad.diagnostics.interceptor.probe_device_access', return_value=probes):
            results = diagnostics.check_input_devices(service_active=True)

        self.assertEqual([diagnostics.WARN], [result.status for result in results])
        self.assertFalse(any(result.blocking for result in results))
        self.assertIn('Macropad service is active', results[0].message)


class ProfileDiagnosticTests(unittest.TestCase):
    def test_missing_profile_directory_is_blocking(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory) / 'profiles'

            results = diagnostics.check_profile_directory(profile_directory)

        self.assertEqual(diagnostics.FAIL, results[0].status)
        self.assertIn('does not exist', results[0].message)

    def test_read_only_profile_directory_still_passes_listening_check(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = Path(temp_directory)
            (profile_directory / 'macros.yml').write_text('profile')

            def access(path, mode):
                return not (Path(path) == profile_directory and mode == diagnostics.os.W_OK)

            with patch('macropad.diagnostics.os.access', side_effect=access):
                results = diagnostics.check_profile_directory(profile_directory)

        self.assertEqual(
            [diagnostics.PASS, diagnostics.INFO], [result.status for result in results]
        )
        self.assertIn('read-only', results[1].message)


class OptionalDiagnosticTests(unittest.TestCase):
    def test_disabled_notifications_need_no_remediation(self):
        with patch(
            'macropad.diagnostics.notifications.check_availability',
            return_value='disabled by --no-notifications',
        ):
            result = diagnostics.check_notifications()

        self.assertEqual(diagnostics.INFO, result.status)
        self.assertEqual('Desktop notifications are disabled.', result.message)
        self.assertIsNone(result.remediation)

    def test_notification_failure_is_informational(self):
        with patch(
            'macropad.diagnostics.notifications.check_availability',
            return_value='session bus unavailable',
        ):
            result = diagnostics.check_notifications()

        self.assertEqual(diagnostics.INFO, result.status)
        self.assertFalse(result.blocking)
        self.assertIn('poor-mans-macropad[notifications]', result.remediation)

    def test_loaded_user_service_reports_fragment_path(self):
        result = diagnostics.check_service(
            '/home/demo/.config/systemd/user/macropad.service',
            True,
            None,
        )

        self.assertEqual(diagnostics.PASS, result.status)
        self.assertIn('/home/demo/.config/systemd/user/macropad.service', result.message)
        self.assertIn('(active)', result.message)

    def test_unset_session_environment_is_informational(self):
        results = diagnostics.check_environment({}, None)

        self.assertEqual(
            [diagnostics.INFO, diagnostics.INFO, diagnostics.INFO],
            [result.status for result in results],
        )
        self.assertIn('DISPLAY=unset', results[2].message)

    def test_graphical_session_environment_passes(self):
        results = diagnostics.check_environment(
            {
                'PATH': '/usr/bin',
                'WAYLAND_DISPLAY': 'wayland-0',
                'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
            },
            '/home/demo/bin:/usr/bin',
        )

        self.assertEqual(
            [diagnostics.PASS, diagnostics.PASS, diagnostics.PASS],
            [result.status for result in results],
        )
        self.assertIn('/home/demo/bin:/usr/bin', results[1].message)
        self.assertIsNone(results[2].remediation)


if __name__ == '__main__':
    unittest.main()
