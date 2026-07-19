import errno
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import evdev
from evdev import InputDevice, ecodes

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


@dataclass(frozen=True)
class DetectedInput:
    device_name: str
    key_name: str
    path: str


def probe_device_access(check_grab: bool = True) -> list[DeviceAccessProbe]:
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
            if not check_grab:
                probes.append(DeviceAccessProbe(path=path, device_name=device.name))
                continue

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


def matching_device_paths(device_name: str, error_callback=None) -> list[str]:
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
            if error_callback is not None:
                error_callback(path, error)
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


def _key_name(code: int) -> str:
    key_name = ecodes.KEY.get(code, f'KEY_{code}')
    if isinstance(key_name, list):
        return key_name[0] if key_name else f'KEY_{code}'
    return key_name


def _wait_for_key(
    paths: Callable[[], list[str]],
    deadline: float,
    timeout_message: str,
    require_release: bool = False,
) -> tuple[InputDevice, int]:
    devices = {}
    released_paths = set()

    try:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(timeout_message)

            current_paths = set(paths())
            for path in set(devices) - current_paths:
                devices.pop(path).close()
                released_paths.discard(path)

            for path in sorted(current_paths - set(devices)):
                try:
                    devices[path] = InputDevice(path)
                except OSError as error:
                    if error.errno not in DEVICE_GONE_ERRNOS:
                        raise

            for path, device in list(devices.items()):
                try:
                    if require_release and path not in released_paths:
                        while device.read_one():
                            pass
                        if not device.active_keys():
                            released_paths.add(path)
                        continue

                    active_keys = device.active_keys()
                    if active_keys:
                        return device, active_keys[0]

                    while event := device.read_one():
                        if event.type == ecodes.EV_KEY and event.value == 1:
                            return device, event.code
                except OSError as error:
                    if error.errno not in DEVICE_GONE_ERRNOS:
                        raise
                    device.close()
                    del devices[path]
                    released_paths.discard(path)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(timeout_message)
            time.sleep(min(0.3, remaining))
    finally:
        for device in devices.values():
            device.close()


def detect(timeout: float = 60.0) -> DetectedInput:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a finite number greater than zero')

    deadline = time.monotonic() + timeout
    known_paths = set(evdev.list_devices())
    candidate_paths = set()

    def newly_connected_paths() -> list[str]:
        current_paths = set(evdev.list_devices())
        candidate_paths.intersection_update(current_paths)
        candidate_paths.update(current_paths - known_paths)
        known_paths.intersection_update(current_paths)
        return sorted(candidate_paths)

    logger.info('detecting newly connected input device')
    device, key_code = _wait_for_key(
        newly_connected_paths,
        deadline,
        f'No reconnected device and key press were detected within {timeout:g} seconds.',
    )
    print_device_info(device)
    return DetectedInput(device.name, _key_name(key_code), device.path)


def capture_key(device_name: str, timeout: float = 60.0) -> DetectedInput:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a finite number greater than zero')

    logger.info('waiting for another key press', extra={'device': device_name})
    device, key_code = _wait_for_key(
        lambda: matching_device_paths(device_name),
        time.monotonic() + timeout,
        f'No key press from {device_name!r} was detected within {timeout:g} seconds.',
        require_release=True,
    )
    return DetectedInput(device.name, _key_name(key_code), device.path)


def listen(device_name, handler, shutdown_event, status_callback=None):
    devices = {}
    last_scan = 0

    def report(state: str, paths=(), error: str | None = None) -> None:
        if status_callback is not None:
            status_callback(state, tuple(sorted(paths)), error)

    try:
        while not shutdown_event.is_set():
            current_time = time.monotonic()
            if not devices and current_time - last_scan >= 0.3:
                scan_failed = False

                def report_scan_error(path: str, error: OSError) -> None:
                    nonlocal scan_failed
                    scan_failed = True
                    report('error', (path,), str(error))

                matching_paths = matching_device_paths(device_name, report_scan_error)
                if matching_paths:
                    report('opening', matching_paths)
                elif not scan_failed:
                    report('waiting')
                for path in matching_paths:
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
                            report('error', (path,), str(error))
                            raise
                        logger.info(
                            'input device disappeared before grab',
                            extra={'device': device_name, 'path': path},
                        )
                        continue
                    _clear_device_error('grab', path)
                    devices[path] = device
                if devices:
                    report('listening', devices)
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
                    report('listening' if devices else 'waiting', devices)

            handler.tick()
            time.sleep(0.01)
    finally:
        for device in devices.values():
            device.close()


def monitor(device_name, event_callback, status_callback, shutdown_event):
    devices = {}
    last_scan = 0

    try:
        while not shutdown_event.is_set():
            current_time = time.monotonic()
            if current_time - last_scan >= 0.3:
                for path in matching_device_paths(device_name):
                    if path in devices:
                        continue

                    try:
                        device = InputDevice(path)
                    except OSError as error:
                        if error.errno in DEVICE_GONE_ERRNOS:
                            continue
                        _log_device_error(error, 'open', path, device_name)
                        continue
                    devices[path] = device
                    status_callback('connected', path)
                last_scan = current_time

            for path, device in list(devices.items()):
                try:
                    while not shutdown_event.is_set() and (event := device.read_one()):
                        event_callback(path, event)
                except OSError as error:
                    if error.errno not in DEVICE_GONE_ERRNOS:
                        _log_device_error(error, 'read', path, device_name)
                        raise
                    device.close()
                    del devices[path]
                    status_callback('disconnected', path)

            time.sleep(0.01)
    finally:
        for device in devices.values():
            device.close()
