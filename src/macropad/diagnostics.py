import errno
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import interceptor, notifications

PASS = 'PASS'
FAIL = 'FAIL'
WARN = 'WARN'
INFO = 'INFO'


@dataclass(frozen=True)
class DiagnosticResult:
    status: str
    name: str
    message: str
    remediation: str | None = None

    @property
    def blocking(self) -> bool:
        return self.status == FAIL


def check_input_devices(service_active: bool) -> list[DiagnosticResult]:
    probes = interceptor.probe_device_access()
    if not probes:
        return [
            DiagnosticResult(
                FAIL,
                'Input devices',
                'No /dev/input/event* devices were found.',
                'Connect a keyboard and confirm the evdev kernel interface is available.',
            )
        ]

    results = []
    accessible_count = 0
    for probe in probes:
        if probe.error_number is None:
            accessible_count += 1
            continue

        label = probe.device_name or probe.path or 'Input devices'
        if probe.error_number in (errno.ENOENT, errno.ENODEV):
            results.append(
                DiagnosticResult(
                    INFO,
                    label,
                    f'Device disappeared during the {probe.operation} check.',
                )
            )
        elif probe.error_number == errno.EACCES:
            results.append(
                DiagnosticResult(
                    FAIL,
                    label,
                    f'Permission denied while attempting to {probe.operation} {probe.path}.',
                    'Grant this user input-device access, then log out and back in. Input access '
                    'can expose every keystroke, including passwords.',
                )
            )
        elif probe.error_number == errno.EBUSY:
            if service_active:
                results.append(
                    DiagnosticResult(
                        WARN,
                        label,
                        f'{probe.path} is exclusively grabbed while the Macropad service is active.',
                        'This is expected for devices owned by Macropad. Stop the service and rerun '
                        'doctor to rule out another input grabber.',
                    )
                )
            else:
                results.append(
                    DiagnosticResult(
                        FAIL,
                        label,
                        f'{probe.path} is already exclusively grabbed.',
                        'Stop any input grabber, then run doctor again.',
                    )
                )
        else:
            results.append(
                DiagnosticResult(
                    FAIL,
                    label,
                    f'Could not {probe.operation} {probe.path}: {probe.error}',
                    'Check the device path and kernel log for the underlying input error.',
                )
            )

    if accessible_count:
        results.insert(
            0,
            DiagnosticResult(
                PASS,
                'Input devices',
                f'{accessible_count} device(s) can be opened and exclusively grabbed.',
            ),
        )
    elif not results or all(result.status == INFO for result in results):
        results.append(
            DiagnosticResult(
                FAIL,
                'Input devices',
                'No stable input device could be opened and exclusively grabbed.',
                'Reconnect the keyboard and run doctor again.',
            )
        )
    return results


def check_profile_directory(profile_directory: Path) -> list[DiagnosticResult]:
    if not profile_directory.exists():
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'{profile_directory} does not exist.',
                'Create the directory and add a .yml profile; see README.md#profile-format.',
            )
        ]
    if not profile_directory.is_dir():
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'{profile_directory} is not a directory.',
                'Replace it with a directory containing .yml profiles.',
            )
        ]
    if not os.access(profile_directory, os.R_OK | os.X_OK):
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'{profile_directory} is not readable.',
                'Grant this user read and directory traversal access.',
            )
        ]

    try:
        profile_paths = sorted(profile_directory.glob('*.yml'))
    except OSError as error:
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'Could not inspect {profile_directory}: {error}',
                'Check directory ownership and permissions.',
            )
        ]
    if not profile_paths:
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'{profile_directory} contains no .yml profiles.',
                'Add a profile and run macropad validate.',
            )
        ]

    unreadable_paths = [path for path in profile_paths if not os.access(path, os.R_OK)]
    if unreadable_paths:
        return [
            DiagnosticResult(
                FAIL,
                'Profile directory',
                f'{unreadable_paths[0]} is not readable.',
                'Grant this user read access to every profile file.',
            )
        ]

    results = [
        DiagnosticResult(
            PASS,
            'Profile directory',
            f'{len(profile_paths)} readable profile(s) found in {profile_directory}.',
        )
    ]
    if not os.access(profile_directory, os.W_OK):
        results.append(
            DiagnosticResult(
                INFO,
                'Profile directory writes',
                'The profile directory is read-only; listening works, but init cannot write here.',
            )
        )
    return results


def check_notifications() -> DiagnosticResult:
    error = notifications.check_availability()
    if error is None:
        return DiagnosticResult(PASS, 'Notifications', 'Desktop notifications are available.')
    return DiagnosticResult(
        INFO,
        'Notifications',
        f'Desktop notifications are unavailable: {error}',
        'This is optional; configure a graphical session and DBus only if notifications are needed.',
    )


def check_executable() -> DiagnosticResult:
    executable = shutil.which('macropad')
    if executable:
        return DiagnosticResult(PASS, 'Executable', f'macropad resolves to {executable}.')
    return DiagnosticResult(
        INFO,
        'Executable',
        'macropad is not available on PATH outside the current invocation.',
        'Install the tool with uv tool install poor-mans-macropad.',
    )


def check_service(
    service_path: str | None,
    service_active: bool,
    error: str | None,
) -> DiagnosticResult:
    if service_path:
        state = 'active' if service_active else 'inactive'
        return DiagnosticResult(PASS, 'User service', f'Loaded from {service_path} ({state}).')
    return DiagnosticResult(
        INFO,
        'User service',
        error or 'The macropad systemd user service is not installed.',
        'Run macropad service install.',
    )


def check_environment(
    environ: Mapping[str, str],
    service_action_path: str | None,
) -> list[DiagnosticResult]:
    path = environ.get('PATH')
    path_result = DiagnosticResult(
        PASS if path else INFO,
        'Current PATH',
        f'PATH={path}' if path else 'PATH is unset for the current process.',
    )
    service_path_result = DiagnosticResult(
        PASS if service_action_path else INFO,
        'Service action PATH',
        f'PATH={service_action_path}'
        if service_action_path
        else 'The service action PATH is unavailable.',
        None
        if service_action_path
        else 'Install the user service to inspect the environment inherited by service actions.',
    )
    session_variables = ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS')
    session_state = ', '.join(
        f'{name}={"set" if environ.get(name) else "unset"}' for name in session_variables
    )
    session_available = bool(
        (environ.get('DISPLAY') or environ.get('WAYLAND_DISPLAY'))
        and environ.get('DBUS_SESSION_BUS_ADDRESS')
    )
    session_result = DiagnosticResult(
        PASS if session_available else INFO,
        'Session environment',
        session_state,
        None
        if session_available
        else 'Unset session variables affect desktop notifications and graphical actions, not '
        'input listening.',
    )
    return [path_result, service_path_result, session_result]


def run_checks(
    profile_directory: Path,
    service_path: str | None,
    service_active: bool,
    service_error: str | None,
    service_action_path: str | None,
) -> list[DiagnosticResult]:
    return [
        *check_input_devices(service_active),
        *check_profile_directory(profile_directory),
        check_notifications(),
        check_executable(),
        check_service(service_path, service_active, service_error),
        *check_environment(os.environ, service_action_path),
    ]
