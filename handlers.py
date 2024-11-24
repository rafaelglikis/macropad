import subprocess
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

import utils
from utils import debounce


class Handler(Protocol):
    """
    Protocol for Event handlers
    """

    def handle(self, e: InputEvent) -> None:
        """
        :param e:  Event to handle
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
        self.layer_once = False
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

        print(self.active_layer, self.layer_used)
        if self.active_layer and self.layer_once and self.layer_used:
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
        if self.active_layer and code != self.layer_activation_key:
            self.layer_used = True

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
            if isinstance(command, str) and command.startswith('!'):
                self.execute_handler_command(command[1:], code)
            else:
                print(f" - Executing command: {command}")
                self.notify("Executing", command)
                utils.daemonize_and_run_command(command)

    def activate_layer(self, layer_name, activation_key_code, once=False):
        if layer_name in self.layers:
            self.active_layer = layer_name
            self.layer_activation_key = activation_key_code
            self.layer_used = False
            self.layer_once = once
            print(f"Layer '{layer_name}' activated {'(once)' if once else '(persistent)'}")
            self.notify("Layer Activated", f"Layer '{layer_name}' is now active")
        else:
            print(f"Layer '{layer_name}' not found")

    def deactivate_layer(self):
        layer = self.active_layer
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        print(f"Layer '{layer}' deactivated")
        if layer:
            self.notify("Layer Deactivated", f"Layer '{layer}' is now deactivated")
        else:
            self.notify("Layer Deactivated", "No layer was active")

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
            is_even = i % 2 == 0
            expected_event = e.key_down if is_even else e.key_up
            if expected_event != recent_event.event.value:
                return False
        return True

    def notify(self, title: str, message, *, expire_seconds: float = 3) -> None:
        if not self.notifications:
            return

        subprocess.call(['notify-send', title, message, '-t', str(expire_seconds * 1000)])

    def execute_handler_command(self, command, code):
        command_with_args = command.split(' ')
        command = command_with_args[0]
        if command == 'layer':
            layer_name = command_with_args[1]
            once = len(command_with_args) > 2 and command_with_args[2] == 'once'
            self.activate_layer(layer_name, code, once=once)
        elif command == 'default_layer':
            self.deactivate_layer()
        else:
            print(f"Handler command '{command}' not found")