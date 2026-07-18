import errno
import logging
import time

import evdev
from evdev import InputDevice

logger = logging.getLogger(__name__)


def matching_device_paths(device_name: str) -> list[str]:
    matching_paths = []

    for path in evdev.list_devices():
        try:
            device = InputDevice(path)
        except OSError:
            continue

        try:
            if device.name == device_name:
                matching_paths.append(path)
        finally:
            device.close()

    return matching_paths


def has_device(device_name: str) -> bool:
    return bool(matching_device_paths(device_name))


def print_device_info(device: InputDevice):
    logger.info(
        'input device opened',
        extra={
            'device': device.name,
            'device_info': str(device.info),
            'path': device.path,
        },
    )


def detect() -> str:
    known_paths = set(evdev.list_devices())
    candidate_paths = set()
    logger.info('detecting new input device')
    while not candidate_paths:
        current_paths = set(evdev.list_devices())
        candidate_paths = current_paths - known_paths
        known_paths.intersection_update(current_paths)
        if candidate_paths:
            break
        time.sleep(0.3)

    logger.info('new input device detected')
    logger.info('waiting for key press on new input device')
    while True:
        current_paths = set(evdev.list_devices())
        candidate_paths.intersection_update(current_paths)
        candidate_paths.update(current_paths - known_paths)
        for device_path in sorted(candidate_paths):
            device = None
            try:
                device = InputDevice(device_path)
                if not device.active_keys():
                    continue
                print_device_info(device)
                return device.name
            except OSError as error:
                if error.errno != errno.ENODEV:
                    raise
                candidate_paths.discard(device_path)
            finally:
                if device is not None:
                    device.close()
        time.sleep(0.3)


def listen(device_name, handler, shutdown_event):
    devices = {}
    last_scan = 0

    try:
        while not shutdown_event.is_set():
            current_time = time.monotonic()
            if not devices and current_time - last_scan >= 0.3:
                for path in matching_device_paths(device_name):
                    if path in devices:
                        continue

                    device = None
                    try:
                        device = InputDevice(path)
                        print_device_info(device)
                        device.grab()
                    except OSError as error:
                        if device:
                            device.close()
                        if error.errno != errno.ENODEV:
                            raise
                        continue
                    devices[path] = device
                last_scan = current_time

            for path, device in list(devices.items()):
                try:
                    while not shutdown_event.is_set() and (event := device.read_one()):
                        handler.handle(event)
                except OSError as error:
                    if error.errno != errno.ENODEV:
                        raise
                    logger.warning(
                        'input device lost',
                        extra={'device': device_name, 'path': path},
                    )
                    device.close()
                    del devices[path]

            handler.tick()
            time.sleep(0.01)
    finally:
        for device in devices.values():
            device.close()
