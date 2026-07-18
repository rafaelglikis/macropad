import unittest
from unittest.mock import patch

from macropad import interceptor


class FakeInputDevice:
    def __init__(self, path, name):
        self.path = path
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True


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


if __name__ == '__main__':
    unittest.main()
