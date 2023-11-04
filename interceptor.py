import evdev
from evdev import KeyEvent, InputDevice

from event_handlers import HandlerProtocol


def _find_device(device_id: str) -> InputDevice:
    devices = [InputDevice(path) for path in evdev.list_devices()]

    for device in devices:
        if device.name == device_id or device.path == device_id:
            print(f'Using device {device}')
            return device

    raise NameError(f"Device not found: {device_id}")


def listen(device_id: str, handlers: list[HandlerProtocol]):
    device = _find_device(device_id)
    device.grab()
    for e in device.read_loop():
        event = evdev.categorize(e)
        if isinstance(event, KeyEvent):
            for handler in handlers:
                handler.handle(e)
