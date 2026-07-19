import argparse
import errno
import signal
import threading

from evdev import ecodes

from .. import interceptor
from . import service

EVENT_NAMES = {
    0: 'up',
    1: 'down',
    2: 'repeat',
}


def _key_name(code: int) -> str:
    key_name = ecodes.KEY.get(code, f'KEY_{code}')
    if isinstance(key_name, list):
        if not key_name:
            return f'KEY_{code}'
        primary_name, *aliases = key_name
        if aliases:
            label = 'alias' if len(aliases) == 1 else 'aliases'
            return f'{primary_name} ({label}: {", ".join(aliases)})'
        return primary_name
    return key_name


def list_devices() -> int:
    probes = interceptor.probe_device_access(check_grab=False)
    paths_by_name = {}
    errors = []
    for probe in probes:
        if probe.error_number is None:
            paths_by_name.setdefault(probe.device_name, []).append(probe.path)
        else:
            errors.append(probe)

    for device_name, paths in sorted(paths_by_name.items()):
        path_label = 'event path' if len(paths) == 1 else 'event paths'
        print(f'{device_name} ({len(paths)} {path_label})')
        for path in paths:
            print(f'  {path}')

    for probe in errors:
        if probe.error_number == errno.EACCES:
            message = 'permission denied'
        elif probe.error_number in interceptor.DEVICE_GONE_ERRNOS:
            message = 'device disappeared'
        else:
            message = probe.error or 'unknown error'
        print(f'UNREADABLE {probe.path}: {message}')

    if paths_by_name:
        return 0
    print('No readable input devices found.')
    return 1


def run(args: argparse.Namespace) -> int:
    if args.device is None:
        return list_devices()

    shutdown_requested = threading.Event()

    def request_shutdown(signum, frame):
        shutdown_requested.set()

    signal.signal(signal.SIGTERM, request_shutdown)

    service_info = service.get_info()
    if service_info.active:
        print(
            'Note: the Macropad service is active; stop it if this device produces no events.',
            flush=True,
        )

    def print_status(status: str, path: str) -> None:
        print(f'{status.upper():12} {path}', flush=True)

    def print_event(path: str, event) -> None:
        if event.type != ecodes.EV_KEY:
            return
        event_name = EVENT_NAMES.get(event.value, f'value={event.value}')
        print(f'{event_name:<12} {_key_name(event.code):<24} {path}', flush=True)

    print(f'Waiting for input device {args.device!r}. Press Ctrl+C to stop.', flush=True)
    try:
        interceptor.monitor(
            args.device,
            print_event,
            print_status,
            shutdown_requested,
        )
    except KeyboardInterrupt:
        pass
    return 0
