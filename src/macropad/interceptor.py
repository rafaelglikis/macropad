import errno
import logging
import time
from dataclasses import dataclass

import evdev
from evdev import InputDevice

logger = logging.getLogger(__name__)
DEVICE_GONE_ERRNOS = (errno.ENOENT, errno.ENODEV)
_reported_device_errors: set[tuple[str, str, int | None]] = set()


@dataclass(frozen=True)
class DeviceAccessProbe:
    path: str
    device_name: str | None = None
    operation: str | None = None
    error_number: int | None = None
    error: str | None = None


def probe_device_access() -> list[DeviceAccessProbe]:
    try:
        paths = sorted(evdev.list_devices())
    except OSError as error:
        return [
            DeviceAccessProbe(
                path='/dev/input',
                operation='enumerate',
                error_number=error.errno,
                error=str(error),
            )
        ]

    probes = []
    for path in paths:
        try:
            device = InputDevice(path)
        except OSError as error:
            probes.append(
                DeviceAccessProbe(
                    path=path,
                    operation='open',
                    error_number=error.errno,
                    error=str(error),
                )
            )
            continue

        try:
            try:
                device.grab()
            except OSError as error:
                probes.append(
                    DeviceAccessProbe(
                        path=path,
                        device_name=device.name,
                        operation='grab',
                        error_number=error.errno,
                        error=str(error),
                    )
                )
                continue

            try:
                device.ungrab()
            except OSError as error:
                probes.append(
                    DeviceAccessProbe(
                        path=path,
                        device_name=device.name,
                        operation='ungrab',
                        error_number=error.errno,
                        error=str(error),
                    )
                )
                continue
            probes.append(DeviceAccessProbe(path=path, device_name=device.name))
        finally:
            device.close()
    return probes


def _log_device_error(
    error: OSError,
    operation: str,
    path: str,
    device_name: str | None = None,
) -> None:
    error_key = (operation, path, error.errno)
    if error_key in _reported_device_errors:
        return
    _reported_device_errors.add(error_key)

    if error.errno == errno.EACCES:
        message = 'input device permission denied'
    elif error.errno == errno.EBUSY:
        message = 'input device already exclusively grabbed'
    else:
        message = f'input device {operation} failed'
    logger.error(
        message,
        extra={
            'device': device_name,
            'path': path,
            'error': str(error),
        },
    )


def _clear_device_error(operation: str, path: str) -> None:
    resolved_errors = {
        error_key for error_key in _reported_device_errors if error_key[:2] == (operation, path)
    }
    _reported_device_errors.difference_update(resolved_errors)


def matching_device_paths(device_name: str) -> list[str]:
    matching_paths = []

    for path in evdev.list_devices():
        try:
            device = InputDevice(path)
        except OSError as error:
            if error.errno in DEVICE_GONE_ERRNOS:
                logger.info(
                    'input device disappeared during scan',
                    extra={'path': path},
                )
                continue
            _log_device_error(error, 'open', path)
            continue

        _clear_device_error('open', path)
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
                if error.errno not in DEVICE_GONE_ERRNOS:
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
                        if error.errno not in DEVICE_GONE_ERRNOS:
                            _log_device_error(error, 'grab', path, device_name)
                            raise
                        logger.info(
                            'input device disappeared before grab',
                            extra={'device': device_name, 'path': path},
                        )
                        continue
                    _clear_device_error('grab', path)
                    devices[path] = device
                last_scan = current_time

            for path, device in list(devices.items()):
                try:
                    while not shutdown_event.is_set() and (event := device.read_one()):
                        handler.handle(event)
                except OSError as error:
                    if error.errno not in DEVICE_GONE_ERRNOS:
                        _log_device_error(error, 'read', path, device_name)
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
