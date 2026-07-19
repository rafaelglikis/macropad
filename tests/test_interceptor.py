import errno
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from macropad import interceptor


class FakeInputDevice:
    def __init__(self, path, name, active_keys=()):
        self.path = path
        self.name = name
        self.info = 'device info'
        self._active_keys = active_keys
        self.closed = False
        self.grabbed = False
        self.ungrabbed = False

    def close(self):
        self.closed = True

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.ungrabbed = True

    def read_one(self):
        return None

    def active_keys(self):
        return self._active_keys


class DeviceMatchingTests(unittest.TestCase):
    def setUp(self):
        interceptor._reported_device_errors.clear()

    def test_matching_paths_returns_every_device_with_matching_name(self):
        devices = {
            '/dev/input/event1': FakeInputDevice('/dev/input/event1', 'Macro Keyboard'),
            '/dev/input/event2': FakeInputDevice('/dev/input/event2', 'Macro Keyboard'),
            '/dev/input/event3': FakeInputDevice('/dev/input/event3', 'Other Keyboard'),
        }

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=list(devices)),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
        ):
            matching_paths = interceptor.matching_device_paths('Macro Keyboard')

        self.assertEqual(['/dev/input/event1', '/dev/input/event2'], matching_paths)
        self.assertTrue(all(device.closed for device in devices.values()))

    def test_event_path_is_not_treated_as_device_name(self):
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
        ):
            self.assertFalse(interceptor.has_device(device.path))

        self.assertTrue(device.closed)

    def test_disappearing_device_is_ignored(self):
        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=['/dev/input/event1']),
            patch(
                'macropad.interceptor.InputDevice',
                side_effect=OSError(errno.ENODEV, 'device lost'),
            ),
        ):
            self.assertFalse(interceptor.has_device('Macro Keyboard'))

    def test_permission_failure_is_reported_instead_of_silently_ignored(self):
        error = OSError(errno.EACCES, 'permission denied')

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=['/dev/input/event1']),
            patch('macropad.interceptor.InputDevice', side_effect=error),
            patch('macropad.interceptor.logger') as logger,
        ):
            self.assertFalse(interceptor.has_device('Macro Keyboard'))
            self.assertFalse(interceptor.has_device('Macro Keyboard'))

        logger.error.assert_called_once_with(
            'input device permission denied',
            extra={
                'device': None,
                'path': '/dev/input/event1',
                'error': '[Errno 13] permission denied',
            },
        )

    def test_permission_failure_is_available_to_runtime_status(self):
        error = OSError(errno.EACCES, 'permission denied')
        error_callback = Mock()

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=['/dev/input/event1']),
            patch('macropad.interceptor.InputDevice', side_effect=error),
        ):
            matching_paths = interceptor.matching_device_paths(
                'Macro Keyboard',
                error_callback,
            )

        self.assertEqual([], matching_paths)
        error_callback.assert_called_once_with('/dev/input/event1', error)

    def test_successful_open_allows_a_later_failure_to_be_reported(self):
        error = OSError(errno.EACCES, 'permission denied')
        device = FakeInputDevice('/dev/input/event1', 'Other Keyboard')

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', side_effect=[error, device, error]),
            patch('macropad.interceptor.logger') as logger,
        ):
            self.assertFalse(interceptor.has_device('Macro Keyboard'))
            self.assertFalse(interceptor.has_device('Macro Keyboard'))
            self.assertFalse(interceptor.has_device('Macro Keyboard'))

        self.assertEqual(2, logger.error.call_count)


class DeviceAccessProbeTests(unittest.TestCase):
    def test_probe_can_inspect_device_without_grabbing(self):
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
        ):
            probes = interceptor.probe_device_access(check_grab=False)

        self.assertEqual([interceptor.DeviceAccessProbe(device.path, device.name)], probes)
        self.assertFalse(device.grabbed)
        self.assertFalse(device.ungrabbed)
        self.assertTrue(device.closed)

    def test_probe_grabs_ungrabs_and_closes_accessible_device(self):
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
        ):
            probes = interceptor.probe_device_access()

        self.assertEqual(
            [interceptor.DeviceAccessProbe(device.path, device.name)],
            probes,
        )
        self.assertTrue(device.grabbed)
        self.assertTrue(device.ungrabbed)
        self.assertTrue(device.closed)

    def test_probe_reports_open_and_grab_failures(self):
        busy_device = FakeInputDevice('/dev/input/event2', 'Busy Keyboard')
        busy_device.grab = Mock(side_effect=OSError(errno.EBUSY, 'device busy'))

        def open_device(path):
            if path == '/dev/input/event1':
                raise OSError(errno.EACCES, 'permission denied')
            return busy_device

        with (
            patch(
                'macropad.interceptor.evdev.list_devices',
                return_value=['/dev/input/event1', '/dev/input/event2'],
            ),
            patch('macropad.interceptor.InputDevice', side_effect=open_device),
        ):
            probes = interceptor.probe_device_access()

        self.assertEqual(errno.EACCES, probes[0].error_number)
        self.assertEqual('open', probes[0].operation)
        self.assertEqual(errno.EBUSY, probes[1].error_number)
        self.assertEqual('grab', probes[1].operation)
        self.assertTrue(busy_device.closed)


class DeviceDetectionTests(unittest.TestCase):
    def test_detect_returns_name_and_closes_selected_device(self):
        device = FakeInputDevice('/dev/input/event2', 'Macro Keyboard', active_keys=(30,))

        with (
            patch(
                'macropad.interceptor.evdev.list_devices',
                side_effect=[
                    ['/dev/input/event1'],
                    ['/dev/input/event2'],
                    ['/dev/input/event2'],
                ],
            ),
            patch('macropad.interceptor.InputDevice', return_value=device),
        ):
            detected = interceptor.detect()

        self.assertEqual(
            interceptor.DetectedInput('Macro Keyboard', 'KEY_A', '/dev/input/event2'),
            detected,
        )
        self.assertTrue(device.closed)

    def test_detect_closes_candidates_without_pressed_keys(self):
        inactive_device = FakeInputDevice('/dev/input/event2', 'Inactive Keyboard')
        selected_device = FakeInputDevice('/dev/input/event3', 'Macro Keyboard', active_keys=(30,))
        devices = {
            inactive_device.path: inactive_device,
            selected_device.path: selected_device,
        }

        with (
            patch(
                'macropad.interceptor.evdev.list_devices',
                side_effect=[
                    ['/dev/input/event1'],
                    list(devices),
                    list(devices),
                ],
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
        ):
            detected = interceptor.detect()

        self.assertEqual(
            interceptor.DetectedInput('Macro Keyboard', 'KEY_A', '/dev/input/event3'),
            detected,
        )
        self.assertTrue(inactive_device.closed)
        self.assertTrue(selected_device.closed)

    def test_detect_times_out_under_one_monotonic_deadline(self):
        now = [0.0]
        clock = Mock()
        clock.monotonic.side_effect = lambda: now[0]
        clock.sleep.side_effect = lambda seconds: now.__setitem__(0, now[0] + seconds)

        with (
            patch('macropad.interceptor.evdev.list_devices', return_value=['/dev/input/event1']),
            patch('macropad.interceptor.time', clock),
            self.assertRaisesRegex(TimeoutError, 'within 1 seconds'),
        ):
            interceptor.detect(timeout=1)

    def test_capture_key_waits_for_release_before_accepting_another_press(self):
        device = FakeInputDevice('/dev/input/event2', 'Macro Keyboard')
        event = SimpleNamespace(type=1, code=48, value=1)
        device.active_keys = Mock(side_effect=[(30,), (), ()])
        device.read_one = Mock(side_effect=[None, None, event])

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch('macropad.interceptor.time.sleep'),
        ):
            detected = interceptor.capture_key(device.name, timeout=1)

        self.assertEqual(
            interceptor.DetectedInput('Macro Keyboard', 'KEY_B', '/dev/input/event2'),
            detected,
        )
        self.assertTrue(device.closed)


class DeviceMonitorTests(unittest.TestCase):
    def test_monitor_reads_events_without_grabbing_device(self):
        shutdown_event = threading.Event()
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        event = SimpleNamespace(type=1, code=30, value=1)
        device.read_one = Mock(return_value=event)
        event_callback = Mock(side_effect=lambda path, input_event: shutdown_event.set())
        status_callback = Mock()
        clock = Mock()
        clock.monotonic.return_value = 1.0

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.monitor(
                device.name,
                event_callback,
                status_callback,
                shutdown_event,
            )

        status_callback.assert_called_once_with('connected', device.path)
        event_callback.assert_called_once_with(device.path, event)
        self.assertFalse(device.grabbed)
        self.assertTrue(device.closed)

    def test_monitor_reports_disconnect_and_reconnect(self):
        shutdown_event = threading.Event()
        first_device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        replacement_device = FakeInputDevice('/dev/input/event2', 'Macro Keyboard')
        first_device.read_one = Mock(side_effect=OSError(errno.ENODEV, 'device lost'))
        replacement_device.read_one = Mock(return_value=None)
        devices = {
            first_device.path: first_device,
            replacement_device.path: replacement_device,
        }
        status_updates = []

        def update_status(status, path):
            status_updates.append((status, path))
            if status == 'connected' and path == replacement_device.path:
                shutdown_event.set()

        clock = Mock()
        clock.monotonic.side_effect = [1.0, 1.4]

        with (
            patch(
                'macropad.interceptor.matching_device_paths',
                side_effect=[[first_device.path], [replacement_device.path]],
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.monitor(
                first_device.name,
                Mock(),
                update_status,
                shutdown_event,
            )

        self.assertEqual(
            [
                ('connected', first_device.path),
                ('disconnected', first_device.path),
                ('connected', replacement_device.path),
            ],
            status_updates,
        )
        self.assertFalse(first_device.grabbed)
        self.assertFalse(replacement_device.grabbed)
        self.assertTrue(first_device.closed)
        self.assertTrue(replacement_device.closed)


class ListenerTests(unittest.TestCase):
    def test_scan_permission_failure_reports_error_instead_of_waiting(self):
        shutdown_event = threading.Event()
        status_callback = Mock()
        error = OSError(errno.EACCES, 'permission denied')

        def scan(device_name, error_callback):
            error_callback('/dev/input/event1', error)
            shutdown_event.set()
            return []

        with (
            patch('macropad.interceptor.matching_device_paths', side_effect=scan),
            patch('macropad.interceptor.time.sleep'),
        ):
            interceptor.listen('Macro Keyboard', Mock(), shutdown_event, status_callback)

        status_callback.assert_called_once_with(
            'error',
            ('/dev/input/event1',),
            str(error),
        )

    def test_grab_conflict_is_logged_and_raised(self):
        shutdown_event = threading.Event()
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        error = OSError(errno.EBUSY, 'device busy')
        device.grab = Mock(side_effect=error)
        status_callback = Mock()

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch('macropad.interceptor.logger') as logger,
            self.assertRaises(OSError) as raised,
        ):
            interceptor.listen(device.name, Mock(), shutdown_event, status_callback)

        self.assertIs(error, raised.exception)
        self.assertTrue(device.closed)
        logger.error.assert_called_once_with(
            'input device already exclusively grabbed',
            extra={
                'device': device.name,
                'path': device.path,
                'error': '[Errno 16] device busy',
            },
        )
        self.assertEqual(
            [
                call('opening', (device.path,), None),
                call('error', (device.path,), str(error)),
            ],
            status_callback.call_args_list,
        )

    def test_listener_ticks_handler(self):
        handler = Mock()
        shutdown_event = Mock()
        shutdown_event.is_set.return_value = False

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[]),
            patch('macropad.interceptor.time.sleep', side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                interceptor.listen('Macro Keyboard', handler, shutdown_event)

        handler.tick.assert_called_once_with()

    def test_shutdown_event_closes_grabbed_devices(self):
        shutdown_event = threading.Event()
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        handler = Mock()
        status_callback = Mock()

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch(
                'macropad.interceptor.time.sleep', side_effect=lambda seconds: shutdown_event.set()
            ),
        ):
            interceptor.listen('Macro Keyboard', handler, shutdown_event, status_callback)

        self.assertTrue(device.grabbed)
        self.assertTrue(device.closed)
        self.assertEqual(
            [
                call('opening', (device.path,), None),
                call('listening', (device.path,), None),
            ],
            status_callback.call_args_list,
        )

    def test_partial_disconnect_closes_lost_device_and_keeps_other_device(self):
        shutdown_event = threading.Event()
        lost_device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        healthy_device = FakeInputDevice('/dev/input/event2', 'Macro Keyboard')
        lost_device.read_one = Mock(side_effect=OSError(errno.ENODEV, 'device lost'))
        healthy_device.read_one = Mock(return_value=None)
        devices = {
            lost_device.path: lost_device,
            healthy_device.path: healthy_device,
        }
        handler = Mock()
        clock = Mock()
        clock.monotonic.return_value = 1.0
        clock.sleep.side_effect = lambda seconds: shutdown_event.set()

        with (
            patch(
                'macropad.interceptor.matching_device_paths',
                return_value=list(devices),
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.listen('Macro Keyboard', handler, shutdown_event)

        self.assertTrue(lost_device.closed)
        self.assertTrue(healthy_device.closed)
        healthy_device.read_one.assert_called_once_with()
        handler.tick.assert_called_once_with()

    def test_listener_reconnects_after_all_matching_devices_are_lost(self):
        shutdown_event = threading.Event()
        first_device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        replacement_device = FakeInputDevice('/dev/input/event2', 'Macro Keyboard')
        first_device.read_one = Mock(side_effect=OSError(errno.ENODEV, 'device lost'))
        replacement_device.read_one = Mock(return_value=None)
        devices = {
            first_device.path: first_device,
            replacement_device.path: replacement_device,
        }
        handler = Mock()
        sleep_count = 0

        def request_shutdown_after_reconnect(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 2:
                shutdown_event.set()

        clock = Mock()
        clock.monotonic.side_effect = [1.0, 1.4]
        clock.sleep.side_effect = request_shutdown_after_reconnect

        with (
            patch(
                'macropad.interceptor.matching_device_paths',
                side_effect=[[first_device.path], [replacement_device.path]],
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.listen('Macro Keyboard', handler, shutdown_event)

        self.assertTrue(first_device.grabbed)
        self.assertTrue(first_device.closed)
        self.assertTrue(replacement_device.grabbed)
        self.assertTrue(replacement_device.closed)
        self.assertEqual(2, handler.tick.call_count)


if __name__ == '__main__':
    unittest.main()
