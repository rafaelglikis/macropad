import subprocess

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


def run(action: str) -> int:
    if action == 'logs':
        command = ['journalctl', '--user', '-u', SERVICE_NAME, '-f']
    elif action in SYSTEMCTL_ACTIONS:
        command = ['systemctl', '--user', action, SERVICE_NAME]
    else:
        raise ValueError(f'unsupported service action {action!r}')

    return subprocess.run(command, check=False).returncode
