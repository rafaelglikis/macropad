import threading
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

import utils


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
        """Return the serializable handler configuration."""


class KeyboardHandler:
    """
    Handles keyboard events
    """

    def __init__(self, config):
        self.bindings = config['bindings']
        self.layers = config.get('layers', {})
        for binding in self.bindings:
            if 'layers' in self.bindings[binding]:
                for layer in self.bindings[binding]['layers']:
                    for b in self.bindings[binding]['layers'][layer]:
                        if layer not in self.layers:
                            self.layers[layer] = {}
                        if 'bindings' not in self.layers[layer]:
                            self.layers[layer]['bindings'] = {}
                        if binding not in self.layers[layer]['bindings']:
                            self.layers[layer]['bindings'][binding] = {}
                        self.layers[layer]['bindings'][binding][b] = self.bindings[binding]['layers'][layer][b]
                del self.bindings[binding]['layers']

        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_once_key = None
        self._layer_timer = None
        self._layer_generation = 0
        self.dry_run = config.get('dry_run', False)
        self.notifications = config.get('notifications', False)
        self.event_logs = {}
        self._event_timers = {}
        self._event_timer_lock = threading.Lock()

    @property
    def raw_data(self) -> dict:
        data = {'bindings': self.bindings}
        if self.layers:
            data['layers'] = self.layers
        if self.dry_run:
            data['dry_run'] = True
        if self.notifications:
            data['notifications'] = True
        return data

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
        if isinstance(current_bindings[code], str):
            current_bindings[code] = {
                'up': current_bindings[code]
            }
        if len(current_bindings[code].keys()) == 1 and 'hold' not in current_bindings[code]:
            self.handle_event_now(event, code, current_bindings, layer_generation)
        else:
            self.handle_event(event, code, current_bindings, layer_generation)

    def get_current_layer_bindings(self):
        if self.active_layer and 'bindings' in self.layers[self.active_layer]:
            print(f"Using layer {self.active_layer} bindings")
            return self.layers[self.active_layer]['bindings']

        print("Using base bindings")
        return self.bindings

    def handle_event(self, event: KeyEvent, code, current_bindings, layer_generation=None):
        def handle_debounced_event():
            with self._event_timer_lock:
                if self._event_timers.get(code) is not timer:
                    return
                del self._event_timers[code]
            self.handle_event_now(event, code, current_bindings, layer_generation)

        timer = threading.Timer(0.2, handle_debounced_event)
        timer.daemon = True
        with self._event_timer_lock:
            previous_timer = self._event_timers.get(code)
            if previous_timer:
                previous_timer.cancel()
            self._event_timers[code] = timer
        timer.start()

    def handle_event_now(self, event: KeyEvent, code, current_bindings, layer_generation=None):
        if layer_generation is not None and layer_generation != self._layer_generation:
            self.event_logs.pop(code, None)
            return

        try:
            current_key_bindings = current_bindings[code]
            event_value = self._map_event(event, self.event_logs.get(code, []))
            only_has_key_for_down = len(current_key_bindings.keys()) == 1 and 'down' in current_key_bindings
            if only_has_key_for_down and event_value == 'hold':
                event_value = 'down'

            self.event_logs.pop(code, None)
            if event_value not in current_key_bindings:
                print(f"No keybinding found for '{event_value}' on {event}")
                return

            print(f"Commands found for '{event_value}' on {event}")
            key_bindings = current_key_bindings[event_value]
            if not isinstance(key_bindings, list):
                key_bindings = [key_bindings]
            for command in key_bindings:
                if isinstance(command, str) and command.startswith('^'):
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
            self._cancel_layer_timer()
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
        if layer_name in self.layers:
            self._cancel_layer_timer()
            self._layer_generation += 1
            self.active_layer = layer_name
            self.layer_activation_key = activation_key_code
            self.layer_used = False
            self.layer_once = once
            self._layer_once_key = None
            if once and deactivate_after > 0:
                generation = self._layer_generation
                self._layer_timer = threading.Timer(
                    deactivate_after,
                    self._deactivate_layer_if_current,
                    args=(generation,),
                )
                self._layer_timer.start()
            print(f"Layer '{layer_name}' activated {'(once)' if once else '(persistent)'}")
            utils.send_notification("Layer Activated", f"Layer '{layer_name}' is now active")
        else:
            print(f"Layer '{layer_name}' not found")

    def deactivate_layer(self):
        self._cancel_layer_timer()
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

    def _cancel_layer_timer(self):
        if self._layer_timer:
            self._layer_timer.cancel()
            self._layer_timer = None

    def _cancel_event_timers(self):
        with self._event_timer_lock:
            timers = list(self._event_timers.values())
            self._event_timers.clear()
        for timer in timers:
            timer.cancel()
        self.event_logs.clear()

    def _deactivate_layer_if_current(self, generation):
        if generation == self._layer_generation:
            self.deactivate_layer()

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
