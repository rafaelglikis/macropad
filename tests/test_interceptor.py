import errno
import threading
import unittest
from unittest.mock import Mock, patch

from macropad import interceptor


class FakeInputDevice:
    def __init__(self, path, name, active_keys=()):
        self.path = path
        self.name = name
        self.info = 'device info'
        self._active_keys = active_keys
        self.closed = False
        self.grabbed = False

    def close(self):
        self.closed = True

    def grab(self):
        self.grabbed = True

    def read_one(self):
        return None

    def active_keys(self):
        return self._active_keys


class DeviceMatchingTests(unittest.TestCase):
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
            device_name = interceptor.detect()

        self.assertEqual('Macro Keyboard', device_name)
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
            device_name = interceptor.detect()

        self.assertEqual('Macro Keyboard', device_name)
        self.assertTrue(inactive_device.closed)
        self.assertTrue(selected_device.closed)


class ListenerTests(unittest.TestCase):
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

        with (
            patch('macropad.interceptor.matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch(
                'macropad.interceptor.time.sleep', side_effect=lambda seconds: shutdown_event.set()
            ),
        ):
            interceptor.listen('Macro Keyboard', handler, shutdown_event)

        self.assertTrue(device.grabbed)
        self.assertTrue(device.closed)

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
