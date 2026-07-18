import os
import pathlib
import subprocess
import threading

import notify2


ASSETS_DIR = pathlib.Path(__file__).parent / "assets"
DEFAULT_CONFIG_DIR = pathlib.Path.home() / ".config" / "macropad" / "profiles"

def reap_zombie_processes(signum, frame):
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break


def debounce(wait_time):
    """
    Decorator that will debounce a function so that it is called after wait_time seconds
    If it is called multiple times, will wait for the last call to be debounced and run only this one.
    """

    def decorator(function):
        def debounced(*args, **kwargs):
            def call_function():
                debounced._timer = None
                return function(*args, **kwargs)

            # if we already have a call to the function currently waiting to be executed, reset the timer
            if debounced._timer is not None:
                debounced._timer.cancel()

            # after wait_time, call the function provided to the decorator with its arguments
            debounced._timer = threading.Timer(wait_time, call_function)
            debounced._timer.start()

        debounced._timer = None
        return debounced

    return decorator


def daemonize_and_run_command(command: str) -> None:
    """Run a command detached from the listener."""
    try:
        subprocess.Popen(
            command,
            shell=True,
            cwd='/',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as e:
        print(f"Failed to execute command: {e}")


def send_notification(title: str, message: str, icon_path: str = None):
    """Send a desktop notification, gracefully handling errors."""
    try:
        notification = notify2.Notification(
            summary=title,
            message=message,
            icon=f"{ASSETS_DIR}/macropad.svg",
        )
        notification.show()
    except Exception as e:
        print(f"Notification error: {e}")
