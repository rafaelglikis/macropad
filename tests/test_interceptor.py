import signal
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

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
                patch('macropad.interceptor.time.sleep', side_effect=lambda seconds: shutdown_event.set()),
        ):
            interceptor.listen(profile, shutdown_event)

        self.assertTrue(device.grabbed)
        self.assertTrue(device.closed)
        profile.handler.shutdown.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
