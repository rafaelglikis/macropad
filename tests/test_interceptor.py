import errno
import signal
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from macropad import interceptor


class FakeInputDevice:
    def __init__(self, path, name):
        self.path = path
        self.name = name
        self.info = 'device info'
        self.closed = False
        self.grabbed = False

    def close(self):
        self.closed = True

    def grab(self):
        self.grabbed = True

    def read_one(self):
        return None


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
            matching_paths = interceptor._matching_device_paths('Macro Keyboard')

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


class ListenerTests(unittest.TestCase):
    def test_sigterm_handler_requests_worker_shutdown(self):
        shutdown_event = threading.Event()

        with patch('macropad.interceptor.signal.signal') as install_signal:
            interceptor.install_shutdown_handler(shutdown_event)

        handler = install_signal.call_args.args[1]
        handler(signal.SIGTERM, None)

        install_signal.assert_called_once_with(signal.SIGTERM, handler)
        self.assertTrue(shutdown_event.is_set())

    def test_listener_ticks_and_shuts_down_handler(self):
        profile = SimpleNamespace(
            device='Macro Keyboard',
            handler=Mock(),
        )
        shutdown_event = Mock()
        shutdown_event.is_set.return_value = False

        with (
            patch('macropad.interceptor.install_shutdown_handler'),
            patch('macropad.interceptor._matching_device_paths', return_value=[]),
            patch('macropad.interceptor.time.sleep', side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                interceptor.listen(profile, shutdown_event)

        profile.handler.tick.assert_called_once_with()
        profile.handler.shutdown.assert_called_once_with()

    def test_shutdown_event_closes_grabbed_devices(self):
        shutdown_event = threading.Event()
        device = FakeInputDevice('/dev/input/event1', 'Macro Keyboard')
        profile = SimpleNamespace(
            device='Macro Keyboard',
            handler=Mock(),
        )

        with (
            patch('macropad.interceptor.install_shutdown_handler'),
            patch('macropad.interceptor._matching_device_paths', return_value=[device.path]),
            patch('macropad.interceptor.InputDevice', return_value=device),
            patch(
                'macropad.interceptor.time.sleep', side_effect=lambda seconds: shutdown_event.set()
            ),
        ):
            interceptor.listen(profile, shutdown_event)

        self.assertTrue(device.grabbed)
        self.assertTrue(device.closed)
        profile.handler.shutdown.assert_called_once_with()

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
        profile = SimpleNamespace(device='Macro Keyboard', handler=Mock())
        clock = Mock()
        clock.time.return_value = 1.0
        clock.sleep.side_effect = lambda seconds: shutdown_event.set()

        with (
            patch('macropad.interceptor.install_shutdown_handler'),
            patch(
                'macropad.interceptor._matching_device_paths',
                return_value=list(devices),
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.listen(profile, shutdown_event)

        self.assertTrue(lost_device.closed)
        self.assertTrue(healthy_device.closed)
        healthy_device.read_one.assert_called_once_with()
        profile.handler.tick.assert_called_once_with()

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
        profile = SimpleNamespace(device='Macro Keyboard', handler=Mock())
        sleep_count = 0

        def request_shutdown_after_reconnect(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 2:
                shutdown_event.set()

        clock = Mock()
        clock.time.side_effect = [1.0, 1.0, 1.4, 1.4]
        clock.sleep.side_effect = request_shutdown_after_reconnect

        with (
            patch('macropad.interceptor.install_shutdown_handler'),
            patch(
                'macropad.interceptor._matching_device_paths',
                side_effect=[[first_device.path], [replacement_device.path]],
            ),
            patch('macropad.interceptor.InputDevice', side_effect=devices.get),
            patch('macropad.interceptor.time', clock),
        ):
            interceptor.listen(profile, shutdown_event)

        self.assertTrue(first_device.grabbed)
        self.assertTrue(first_device.closed)
        self.assertTrue(replacement_device.grabbed)
        self.assertTrue(replacement_device.closed)
        self.assertEqual(2, profile.handler.tick.call_count)


if __name__ == '__main__':
    unittest.main()
