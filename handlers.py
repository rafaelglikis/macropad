import os
import resource
import subprocess
import sys
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

from utils import debounce
import signal


def reap_zombie_processes(signum, frame):
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break


signal.signal(signal.SIGCHLD, reap_zombie_processes)


class Handler(Protocol):
    """
    Protocol for Event handlers
    """

    def handle(self, e: InputEvent) -> None:
        """
        :param e:  Event to handle
        """

    @property
    def raw_data(self) -> dict:
        """
        :return: Raw data in dict format
        """


class KeyboardHandler:
    """
    Handles keyboard events
    """

    def __init__(self, config):
        self.bindings = config['bindings']
        self.dry_run = config['dry_run'] if 'dry_run' in config else False
        self.notifications = config['notifications'] if 'notifications' in config else False
        self.event_logs = []

    @property
    def raw_data(self) -> dict:
        raw_data = {
            "bindings": self.bindings,
        }

        if self.notifications:
            raw_data["notifications"] = self.notifications

        if self.dry_run:
            raw_data["dry_run"] = self.dry_run

        return raw_data

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        print()
        if not isinstance(event, KeyEvent):
            return

        code = evdev.ecodes.KEY[e.code]
        if code not in self.bindings:
            print(f'No keybinding found for {event}')
            return

        self.event_logs.append(event)
        if len(self.bindings[code].keys()) == 1 and not 'hold' in self.bindings[code]:
            self.handle_event_now(event, code)
        else:
            self.handle_event(event, code)

    @debounce(0.2)
    def handle_event(self, event: KeyEvent, code):
        self.handle_event_now(event, code)

    @debounce(0.001)
    def handle_event_now(self, event: KeyEvent, code):
        current_key_bindings = self.bindings[code]
        event_value = self._map_event(event)
        only_has_key_for_down = len(self.bindings[code].keys()) == 1 and 'down' in self.bindings[code]
        if only_has_key_for_down and event_value == 'hold':
            event_value = 'down'

        self.event_logs = []
        if event_value not in current_key_bindings:
            print(f"No keybinding found for '{event_value}' on {event}")
            return

        print(f"Commands found for '{event_value}' on {event}")
        key_bindings = current_key_bindings[event_value]
        if not isinstance(key_bindings, list):
            key_bindings = [key_bindings]
        for command in key_bindings:
            print(f" - Executing command: {command}")
            daemonize_and_run_command(command)

    def _map_event(self, e: KeyEvent) -> str:
        if self._is_hold_event(e):
            return 'hold'
        if self.is_nth_tap(e, 3):
            return 'triple_tap'
        if self.is_nth_tap(e, 2):
            return 'double_tap'
        if e.event.value == e.key_up:
            return 'up'
        if e.event.value == e.key_down:
            return 'down'
        return ''

    def _is_hold_event(self, e):
        is_proper_hold_event = e.event.value == e.key_hold
        is_up_event_that_follows_hold_event = (
                len(self.event_logs) >= 2
                and self.event_logs[-2].event.value == e.key_hold
                and self.event_logs[-2].event.code == e.event.code
        )

        return is_proper_hold_event or is_up_event_that_follows_hold_event

    def is_nth_tap(self, e, n):
        history_length = 2 * n
        recent_event_logs = self.event_logs[-history_length:]
        if len(recent_event_logs) < history_length:
            return False
        for i, recent_event in enumerate(recent_event_logs):
            if e.event.code != recent_event.event.code:
                return False
            expected_event = e.key_down if i % 2 == 0 else e.key_up
            if expected_event != recent_event.event.value:
                return False
        return True

    def notify(self, title: str, message, *, expire_seconds: float = 3) -> None:
        if not self.notifications:
            return

        subprocess.call(['notify-send', title, message, '-t', str(expire_seconds * 1000)])


def daemonize_and_run_command(command: str) -> None:
    """Daemonizes the process and executes the given shell command."""
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            return  # Parent process returns to continue the loop
    except OSError as e:
        print(f"First fork failed: {e}", file=sys.stderr)
        return

    # Decouple from parent environment
    os.chdir('/')
    os.umask(0)
    os.setsid()

    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        print(f"Second fork failed: {e}", file=sys.stderr)
        sys.exit(1)

    # In the child process

    # Close all file descriptors except stdin(0), stdout(1), stderr(2)
    max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if max_fd == resource.RLIM_INFINITY:
        max_fd = 1024  # Set a default if unlimited
    os.closerange(3, max_fd)

    # Redirect standard file descriptors to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/dev/null', 'rb', 0) as read_null, open('/dev/null', 'wb', 0) as write_null:
        os.dup2(read_null.fileno(), sys.stdin.fileno())
        os.dup2(write_null.fileno(), sys.stdout.fileno())
        os.dup2(write_null.fileno(), sys.stderr.fileno())

    try:
        # Execute the command
        pipe = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True
        )
        stdout, _ = pipe.communicate()
    except Exception as e:
        print(f"Failed to execute command: {e}", file=sys.stderr)

    sys.exit(0)
