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


def listen(profile: Profile):
    device = _find_device(profile.device)
    device.grab()
    for e in device.read_loop():
        profile.handler.handle(e)
