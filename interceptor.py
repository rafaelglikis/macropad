import time

from profile import Profile

import evdev
from evdev import InputDevice


def _find_device(device_id: str) -> list[InputDevice]:
    devices = [InputDevice(path) for path in evdev.list_devices()]

    devices_to_return = []
    for device in devices:
        if device.name == device_id or device.path == device_id:
            print(f'Using device {device}')
            devices_to_return.append(device)

    if not devices_to_return:
        raise NameError(f"Device not found: {device_id}")

    return devices_to_return


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
    devices = _find_device(profile.device)
    for device in devices:
        print_device_info(device)
        device.grab()

    while True:
        for device in devices:
            e = device.read_one()
            if e:
                profile.handler.handle(e)
