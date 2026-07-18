import time
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

from . import utils
from .config import BindingConfig, KeyboardConfig


EVENT_DEBOUNCE_SECONDS = 0.2
DELAYED_EVENTS = {'hold', 'double_tap', 'triple_tap'}


class Handler(Protocol):
    """
    Protocol for Event handlers
    """

    def handle(self, e: InputEvent) -> None:
        """
        :param e:  Event to handle
        """

    def tick(self) -> None:
        """Process delayed state transitions that are ready to run."""


class KeyboardHandler:
    """
    Handles keyboard events
    """

    def __init__(self, config: KeyboardConfig, clock=time.monotonic):
        self._clock = clock
        self.config = config

        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_once_key = None
        self._layer_deadline = None
        self._layer_generation = 0
        self.event_logs = {}
        self._pending_events = {}

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        if not isinstance(event, KeyEvent):
            return

        code = evdev.ecodes.KEY[e.code]

        # Get current bindings (either from active layer or base bindings)
        current_bindings = self.get_current_layer_bindings()
        if code not in current_bindings:
            print(f'No keybinding found for {event}')
            return

        layer_generation = self._layer_generation if self.active_layer else None
        if not self._claim_one_shot_layer(code):
            return

        self.event_logs.setdefault(code, []).append(event)
        binding = current_bindings[code]
        is_simple_binding = (
            len(binding.actions) == 1
            and binding.actions.keys().isdisjoint(DELAYED_EVENTS)
        )
        if is_simple_binding:
            self.handle_event_now(event, code, binding, layer_generation)
        else:
            self.handle_event(event, code, binding, layer_generation)

    def get_current_layer_bindings(self):
        if self.active_layer:
            print(f"Using layer {self.active_layer} bindings")
            return self.config.layers[self.active_layer].bindings

        print("Using base bindings")
        return self.config.bindings

    def handle_event(self, event: KeyEvent, code, binding: BindingConfig, layer_generation=None):
        self._pending_events[code] = (
            self._clock() + EVENT_DEBOUNCE_SECONDS,
            event,
            binding,
            layer_generation,
        )

    def tick(self):
        now = self._clock()
        due_codes = sorted(
            (
                code
                for code, (deadline, _, _, _) in self._pending_events.items()
                if deadline <= now
            ),
            key=lambda code: self._pending_events[code][0],
        )
        for code in due_codes:
            _, event, binding, layer_generation = self._pending_events.pop(code)
            self.handle_event_now(event, code, binding, layer_generation)

        if self._layer_deadline is not None and self._layer_deadline <= now:
            self.deactivate_layer()

    def handle_event_now(self, event: KeyEvent, code, binding: BindingConfig, layer_generation=None):
        if layer_generation is not None and layer_generation != self._layer_generation:
            self.event_logs.pop(code, None)
            return

        try:
            event_value = self._map_event(event, self.event_logs.get(code, []))
            only_has_key_for_down = len(binding.actions) == 1 and 'down' in binding.actions
            if only_has_key_for_down and event_value == 'hold':
                event_value = 'down'

            self.event_logs.pop(code, None)
            if event_value not in binding.actions:
                print(f"No keybinding found for '{event_value}' on {event}")
                return

            print(f"Commands found for '{event_value}' on {event}")
            for command in binding.actions[event_value]:
                if command.startswith('^'):
                    self.execute_handler_command(command[1:], code)
                else:
                    print(f"Executing command '{command}' for '{event_value}' on {event}")
                    utils.daemonize_and_run_command(command)
        finally:
            self._finish_one_shot_layer(event, code, layer_generation)

    def _claim_one_shot_layer(self, code):
        if not self.active_layer or not self.layer_once or code == self.layer_activation_key:
            return True

        if self._layer_once_key is None:
            self._layer_once_key = code
            self.layer_used = True
            self._cancel_layer_deadline()
            return True

        if code == self._layer_once_key:
            return True

        print(f"One-shot layer '{self.active_layer}' is already in use by {self._layer_once_key}")
        return False

    def _finish_one_shot_layer(self, event, code, layer_generation):
        if (
                event.event.value == event.key_up
                and self.active_layer
                and self.layer_once
                and code == self._layer_once_key
                and layer_generation == self._layer_generation
        ):
            self.deactivate_layer()

    def activate_layer(self, layer_name, activation_key_code, once=False, deactivate_after=5):
        if layer_name in self.config.layers:
            self._cancel_layer_deadline()
            self._layer_generation += 1
            self.active_layer = layer_name
            self.layer_activation_key = activation_key_code
            self.layer_used = False
            self.layer_once = once
            self._layer_once_key = None
            if once and deactivate_after > 0:
                self._layer_deadline = self._clock() + deactivate_after
            print(f"Layer '{layer_name}' activated {'(once)' if once else '(persistent)'}")
            utils.send_notification("Layer Activated", f"Layer '{layer_name}' is now active")
        else:
            print(f"Layer '{layer_name}' not found")

    def deactivate_layer(self):
        self._cancel_layer_deadline()
        layer = self.active_layer
        self._layer_generation += 1
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_once_key = None
        print(f"Layer '{layer}' deactivated")
        if layer:
            utils.send_notification("Layer Deactivated", f"Layer '{layer}' is now deactivated")
        else:
            utils.send_notification("Layer Deactivated", "No layer was active")

    def _cancel_layer_deadline(self):
        self._layer_deadline = None

    def _map_event(self, e: KeyEvent, event_logs) -> str:
        if self._is_hold_event(e, event_logs):
            return 'hold'
        if self.is_nth_tap(e, 3, event_logs):
            return 'triple_tap'
        if self.is_nth_tap(e, 2, event_logs):
            return 'double_tap'
        if e.event.value == e.key_up:
            return 'up'
        if e.event.value == e.key_down:
            return 'down'
        return ''

    def _is_hold_event(self, e, event_logs):
        is_proper_hold_event = e.event.value == e.key_hold
        is_up_event_that_follows_hold_event = (
                len(event_logs) >= 2
                and event_logs[-2].event.value == e.key_hold
                and event_logs[-2].event.code == e.event.code
        )

        return is_proper_hold_event or is_up_event_that_follows_hold_event

    def is_nth_tap(self, e, n, event_logs):
        history_length = 2 * n
        recent_event_logs = event_logs[-history_length:]
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
