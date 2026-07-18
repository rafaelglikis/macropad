import pathlib
import subprocess
from importlib.resources import files

import notify2


DEFAULT_ICON = files('macropad').joinpath('assets/macropad.svg')
DEFAULT_CONFIG_DIR = pathlib.Path.home() / ".config" / "macropad" / "profiles"
_command_processes: list[subprocess.Popen] = []


def daemonize_and_run_command(command: str) -> None:
    """Run a command detached from the listener."""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd='/',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        _command_processes.append(process)
    except OSError as e:
        print(f"Failed to execute command: {e}")


def reap_finished_commands() -> None:
    _command_processes[:] = [
        process
        for process in _command_processes
        if process.poll() is None
    ]


def send_notification(title: str, message: str, icon_path: str = None):
    """Send a desktop notification, gracefully handling errors."""
    try:
        notification = notify2.Notification(
            summary=title,
            message=message,
            icon=str(icon_path or DEFAULT_ICON),
        )
        notification.show()
    except Exception as e:
        print(f"Notification error: {e}")
