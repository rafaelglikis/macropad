import time

from profile import Profile

import evdev
from evdev import InputDevice


def _find_device(device_id: str) -> InputDevice:
    devices = [InputDevice(path) for path in evdev.list_devices()]

    for device in devices:
        if device.name == device_id or device.path == device_id:
            print(f'Using device {device}')
            return device

    raise NameError(f"Device not found: {device_id}")


def print_device_info(device: InputDevice):
    print('----------- Input device info -----------')
    print(f"name: '{device.name}'")
    print(f"path: '{device.path}'")
    print(f"info: '{device.info}'")
    print('-----------------------------------------')


def detect() -> InputDevice:
    initial_devices = evdev.list_devices()
    devices = evdev.list_devices()

    print('Detecting new devices, please connect your device.')
    while True:
        if len(devices) > len(initial_devices):
            break
        time.sleep(0.3)
        initial_devices, devices = devices, evdev.list_devices()

    print('New devices detected!')
    new_devices = list(set(devices) - set(initial_devices))

    print('Press and hold any key on your device.')
    while True:
        for device_path in new_devices:
            device = InputDevice(device_path)
            if device.active_keys():
                print_device_info(device)
                return device
        time.sleep(0.3)



def listen(profile: Profile):
    device = _find_device(profile.device)
    print_device_info(device)
    device.grab()
    for e in device.read_loop():
        profile.handler.handle(e)
