
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
        self.layers = config.get('layers', {})
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.dry_run = config.get('dry_run', False)
        self.notifications = config.get('notifications', False)
        self.event_logs = []

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        print()
        if not isinstance(event, KeyEvent):
            return

        code = evdev.ecodes.KEY[e.code]

        # Get current bindings (either from active layer or base bindings)
        current_bindings = self.get_current_layer_bindings()
        if code not in current_bindings:
            print(f'No keybinding found for {event}')
            return

        self.event_logs.append(event)
        if len(current_bindings[code].keys()) == 1 and 'hold' not in current_bindings[code]:
            self.handle_event_now(event, code, current_bindings)
        else:
            self.handle_event(event, code, current_bindings)

        if self.active_layer and self.layer_used:
            self.deactivate_layer()

    def get_current_layer_bindings(self):
        if self.active_layer and 'bindings' in self.layers[self.active_layer]:
            print(f"Using layer {self.active_layer} bindings")
            return self.layers[self.active_layer]['bindings']

        print("Using base bindings")
        return self.bindings

    @debounce(0.2)
    def handle_event(self, event: KeyEvent, code, current_bindings):
        self.handle_event_now(event, code, current_bindings)

    @debounce(0.001)
    def handle_event_now(self, event: KeyEvent, code, current_bindings):
        current_key_bindings = current_bindings[code]
        event_value = self._map_event(event)
        only_has_key_for_down = len(current_key_bindings.keys()) == 1 and 'down' in current_key_bindings
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
            if isinstance(command, str) and command.startswith('!layer '):
                # Activate the specified layer
                layer_name = command.split(' ', 1)[1]
                self.activate_layer(layer_name, code)
            else:
                print(f" - Executing command: {command}")
                daemonize_and_run_command(command)

        # If a layer is active and we have processed a key press that is not the activation key
        if self.active_layer and code != self.layer_activation_key:
            self.layer_used = True

    def activate_layer(self, layer_name, activation_key_code):
        if layer_name in self.layers:
            self.active_layer = layer_name
            self.layer_activation_key = activation_key_code
            self.layer_used = False  # Indicates whether the layer has been used for a key press
            print(f"Layer '{layer_name}' activated")
            self.notify("Layer Activated", f"Layer '{layer_name}' is now active")
        else:
            print(f"Layer '{layer_name}' not found")

    def deactivate_layer(self):
        print(f"Layer '{self.active_layer}' deactivated")
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False

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
