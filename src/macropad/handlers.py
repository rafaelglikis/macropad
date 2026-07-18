import logging
import time
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

from . import utils
from .actions import ActionExecutor
from .config import BindingConfig, KeyboardConfig


EVENT_DEBOUNCE_SECONDS = 0.2
DELAYED_EVENTS = {'hold', 'double_tap', 'triple_tap'}
logger = logging.getLogger(__name__)


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

    def shutdown(self) -> None:
        """Release resources owned by the handler."""


class KeyboardHandler:
    """
    Handles keyboard events
    """

    def __init__(
            self,
            config: KeyboardConfig,
            clock=time.monotonic,
            action_executor: ActionExecutor | None = None,
            device: str | None = None,
    ):
        self._clock = clock
        self.config = config
        self.device = device
        self.action_executor = (
            action_executor
            if action_executor is not None
            else ActionExecutor(device=device)
        )

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
            logger.debug(
                'no key binding for input event',
                extra=self._context(key=code, event=str(event)),
            )
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
            logger.debug(
                'using layer bindings',
                extra=self._context(layer=self.active_layer),
            )
            return self.config.layers[self.active_layer].bindings

        logger.debug('using base bindings', extra=self._context())
        return self.config.bindings

    def handle_event(self, event: KeyEvent, code, binding: BindingConfig, layer_generation=None):
        self._pending_events[code] = (
            self._clock() + EVENT_DEBOUNCE_SECONDS,
            event,
            binding,
            layer_generation,
        )

    def tick(self):
        self.action_executor.tick()
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

    def shutdown(self):
        self.action_executor.shutdown()

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
                logger.debug(
                    'no binding for resolved event',
                    extra=self._context(key=code, event=event_value),
                )
                return

            logger.debug(
                'actions resolved for input event',
                extra=self._context(key=code, event=event_value),
            )
            for command in binding.actions[event_value]:
                if command.startswith('^'):
                    self.execute_handler_command(command[1:], code)
                else:
                    logger.info(
                        'submitting action',
                        extra=self._context(
                            key=code,
                            event=event_value,
                            command=command,
                        ),
                    )
                    self.action_executor.submit(command)
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

        logger.debug(
            'one-shot layer already claimed',
            extra=self._context(layer=self.active_layer, key=self._layer_once_key),
        )
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
            logger.info(
                'layer activated',
                extra=self._context(
                    layer=layer_name,
                    mode='once' if once else 'persistent',
                ),
            )
            utils.send_notification("Layer Activated", f"Layer '{layer_name}' is now active")
        else:
            logger.warning(
                'layer not found',
                extra=self._context(layer=layer_name),
            )

    def deactivate_layer(self):
        self._cancel_layer_deadline()
        layer = self.active_layer
        self._layer_generation += 1
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_once_key = None
        logger.info('layer deactivated', extra=self._context(layer=layer))
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
            logger.warning(
                'handler command not found',
                extra=self._context(command=command, key=code),
            )

    def _context(self, **values) -> dict:
        if self.device is not None:
            values['device'] = self.device
        return values
