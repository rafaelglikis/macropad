import shlex
import subprocess
from dataclasses import dataclass

SERVICE_NAME = 'macropad.service'
SYSTEMCTL_ACTIONS = (
    'enable',
    'disable',
    'start',
    'stop',
    'restart',
    'status',
)
SERVICE_ACTIONS = (
    *SYSTEMCTL_ACTIONS,
    'logs',
)


@dataclass(frozen=True)
class ServiceInfo:
    fragment_path: str | None
    active: bool
    error: str | None = None
    action_path: str | None = None


def get_info() -> ServiceInfo:
    command = [
        'systemctl',
        '--user',
        'show',
        SERVICE_NAME,
        '--property=FragmentPath',
        '--property=ActiveState',
        '--property=Environment',
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError as error:
        return ServiceInfo(None, False, f'systemctl is unavailable: {error}')
    except subprocess.TimeoutExpired:
        return ServiceInfo(
            None,
            False,
            'The systemd user manager did not respond within five seconds.',
        )

    properties = {}
    for line in completed.stdout.splitlines():
        name, separator, value = line.partition('=')
        if separator:
            properties[name] = value
    fragment_path = properties.get('FragmentPath')
    if completed.returncode == 0 and fragment_path:
        try:
            environment = shlex.split(properties.get('Environment', ''))
        except ValueError:
            environment = []
        action_path = next(
            (
                assignment.removeprefix('PATH=')
                for assignment in environment
                if assignment.startswith('PATH=')
            ),
            None,
        )
        return ServiceInfo(
            fragment_path,
            properties.get('ActiveState') == 'active',
            action_path=action_path,
        )
    return ServiceInfo(
        None,
        False,
        'The macropad systemd user service is not installed or unavailable.',
    )


def run(action: str) -> int:
    if action == 'logs':
        command = ['journalctl', '--user', '-u', SERVICE_NAME, '-f']
    elif action in SYSTEMCTL_ACTIONS:
        command = ['systemctl', '--user', action, SERVICE_NAME]
    else:
        raise ValueError(f'unsupported service action {action!r}')

    return subprocess.run(command, check=False).returncode
