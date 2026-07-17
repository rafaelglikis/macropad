import time

import evdev
from evdev import InputDevice


def _find_device(device_id: str) -> list[InputDevice]:
    devices = [InputDevice(path) for path in evdev.list_devices()]

    devices_to_return = []
    for device in devices:
        if device.name == device_id or device.path == device_id:
            print_device_info(device)
            devices_to_return.append(device)

    if not devices_to_return:
        raise NameError(f"Device not found: {device_id}")

    return devices_to_return


def _matching_device_paths(device_id: str) -> list[str]:
    matching_paths = []

    for path in evdev.list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue

        try:
            if device.name == device_id or device.path == device_id:
                matching_paths.append(path)
        finally:
            device.close()

    return matching_paths


def has_device(device_id: str) -> bool:
    for path in evdev.list_devices():
        device = InputDevice(path)
        try:
            matches = device.name == device_id or device.path == device_id
        finally:
            device.close()

        if matches:
            return True

    return False


def print_device_info(device: InputDevice):
    print(f"Using Device: {device.name} | Path: {device.path} | Info: {device.info}")


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


def listen(profile):
    devices = {}
    last_scan = 0

    try:
        while True:
            current_time = time.time()
            if current_time - last_scan >= 0.3:
                last_scan = current_time

                for path in _matching_device_paths(profile.device):
                    if path in devices:
                        continue

                    device = None
                    try:
                        device = InputDevice(path)
                        print_device_info(device)
                        device.grab()
                    except OSError as e:
                        if device:
                            device.close()
                        if e.errno != 19:
                            raise
                        continue
                    devices[path] = device

            for path, device in list(devices.items()):
                try:
                    e = device.read_one()
                    if e:
                        profile.handler.handle(e)
                except OSError as e:
                    if e.errno != 19:
                        raise
                    print(f'Device {profile.device} lost: {path}')
                    device.close()
                    del devices[path]

            time.sleep(0.01)
    finally:
        for device in devices.values():
            device.close()
