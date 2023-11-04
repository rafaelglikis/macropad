import evdev
from evdev import KeyEvent, InputDevice

from Profile import Profile


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
        event = evdev.categorize(e)
        if isinstance(event, KeyEvent):
            for handler in profile.handlers:
                handler.handle(e)
