import logging
import time
from dataclasses import dataclass, replace

import evdev
from evdev import InputEvent, KeyEvent

from . import notifications
from .actions import ActionExecutor
from .config import BindingConfig, KeyboardConfig

DELAYED_EVENTS = {'hold', 'double_tap', 'triple_tap'}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayerSnapshot:
    name: str
    activation_key: str
    mode: str
    used: bool
    one_shot_key: str | None
    deadline: float | None
    previous: 'LayerSnapshot | None'


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
            action_executor if action_executor is not None else ActionExecutor(device=device)
        )
        self._multi_tap_seconds = config.timing.multi_tap_ms / 1000
        self._one_shot_timeout_seconds = config.timing.one_shot_timeout_ms / 1000

        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_mode = None
        self._layer_once_key = None
        self._layer_deadline = None
        self._momentary_previous = None
        self._layer_generation = 0
        self.event_logs = {}
        self._pending_events = {}

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        if not isinstance(event, KeyEvent):
            return

        code = evdev.ecodes.KEY[e.code]
        if self._handle_activation_key_event(event, code):
            return

        binding, resolved_layer = self._resolve_binding(code)
        if binding is None:
            logger.debug(
                'no key binding for input event',
                extra=self._context(key=code, event=str(event)),
            )
            return

        layer_generation = self._layer_generation if self.active_layer else None
        if not self._claim_one_shot_layer(code):
            return

        self.event_logs.setdefault(code, []).append(event)
        is_simple_binding = len(binding.actions) == 1 and binding.actions.keys().isdisjoint(
            DELAYED_EVENTS
        )
        if is_simple_binding:
            self.handle_event_now(event, code, binding, layer_generation, resolved_layer)
        else:
            self.handle_event(event, code, binding, layer_generation, resolved_layer)

    def _resolve_binding(self, code):
        if self.active_layer:
            layer = self.config.layers[self.active_layer]
            if code in layer.bindings:
                logger.debug(
                    'using layer binding',
                    extra=self._context(layer=self.active_layer, key=code),
                )
                return layer.bindings[code], self.active_layer
            if layer.fallback == 'base' and code in self.config.bindings:
                logger.debug(
                    'using base fallback binding',
                    extra=self._context(layer=self.active_layer, key=code),
                )
                return self.config.bindings[code], 'base'
            return None, None

        if code in self.config.bindings:
            logger.debug('using base binding', extra=self._context(key=code))
            return self.config.bindings[code], 'base'
        return None, None

    def handle_event(
        self,
        event: KeyEvent,
        code,
        binding: BindingConfig,
        layer_generation,
        resolved_layer,
    ):
        self._pending_events[code] = (
            self._clock() + self._multi_tap_seconds,
            event,
            binding,
            layer_generation,
            resolved_layer,
        )

    def tick(self):
        self.action_executor.tick()
        now = self._clock()
        due_codes = sorted(
            (
                code
                for code, (deadline, _, _, _, _) in self._pending_events.items()
                if deadline <= now
            ),
            key=lambda code: self._pending_events[code][0],
        )
        for code in due_codes:
            _, event, binding, layer_generation, resolved_layer = self._pending_events.pop(code)
            self.handle_event_now(event, code, binding, layer_generation, resolved_layer)

        if self._layer_deadline is not None and self._layer_deadline <= now:
            self.deactivate_layer()

    def shutdown(self):
        self.action_executor.shutdown()

    def handle_event_now(
        self,
        event: KeyEvent,
        code,
        binding: BindingConfig,
        layer_generation,
        resolved_layer,
    ):
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
                            layer=resolved_layer,
                        ),
                    )
                    self.action_executor.submit(
                        command,
                        key=code,
                        event=event_value,
                        layer=resolved_layer,
                    )
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

    def activate_layer(
        self,
        layer_name,
        activation_key_code,
        once=False,
        deactivate_after=None,
        mode=None,
    ):
        if layer_name in self.config.layers:
            mode = mode or ('once' if once else 'persistent')
            if (
                mode == 'toggle'
                and self.active_layer == layer_name
                and self._layer_mode == 'toggle'
            ):
                self.deactivate_layer()
                return

            previous = self._snapshot_layer() if mode == 'momentary' else None
            self._cancel_layer_deadline()
            self._layer_generation += 1
            self.active_layer = layer_name
            self.layer_activation_key = activation_key_code
            self.layer_used = False
            self.layer_once = mode == 'once'
            self._layer_mode = mode
            self._layer_once_key = None
            self._momentary_previous = previous
            timeout = (
                self._one_shot_timeout_seconds if deactivate_after is None else deactivate_after
            )
            if self.layer_once and timeout > 0:
                self._layer_deadline = self._clock() + timeout
            logger.info(
                'layer activated',
                extra=self._context(
                    layer=layer_name,
                    mode=mode,
                ),
            )
            if mode != 'momentary':
                notifications.send('Layer Activated', f"Layer '{layer_name}' is now active")
        else:
            logger.warning(
                'layer not found',
                extra=self._context(layer=layer_name),
            )

    def deactivate_layer(self):
        self._cancel_layer_deadline()
        layer = self.active_layer
        mode = self._layer_mode
        self._layer_generation += 1
        self.active_layer = None
        self.layer_activation_key = None
        self.layer_used = False
        self.layer_once = False
        self._layer_mode = None
        self._layer_once_key = None
        self._momentary_previous = None
        logger.info('layer deactivated', extra=self._context(layer=layer))
        if mode != 'momentary':
            if layer:
                notifications.send('Layer Deactivated', f"Layer '{layer}' is now deactivated")
            else:
                notifications.send('Layer Deactivated', 'No layer was active')

    def _handle_activation_key_event(self, event, code):
        event_value = event.event.value
        if self._layer_mode == 'momentary' and code == self.layer_activation_key:
            if event_value == event.key_up:
                self._restore_momentary_layer(code)
            return True
        if self._layer_mode == 'toggle' and code == self.layer_activation_key:
            if event_value == event.key_up:
                self.deactivate_layer()
            return True
        if event_value != event.key_up or self._momentary_previous is None:
            return False

        previous, removed = self._remove_released_momentary(self._momentary_previous, code)
        if removed:
            self._momentary_previous = previous
        return removed

    def _snapshot_layer(self):
        if self.active_layer is None:
            return None
        return LayerSnapshot(
            name=self.active_layer,
            activation_key=self.layer_activation_key,
            mode=self._layer_mode,
            used=self.layer_used,
            one_shot_key=self._layer_once_key,
            deadline=self._layer_deadline,
            previous=self._momentary_previous,
        )

    def _restore_momentary_layer(self, released_key):
        previous = self._momentary_previous
        layer = self.active_layer
        self._layer_generation += 1
        if previous is None:
            self.active_layer = None
            self.layer_activation_key = None
            self.layer_used = False
            self.layer_once = False
            self._layer_mode = None
            self._layer_once_key = None
            self._layer_deadline = None
            self._momentary_previous = None
            restored_layer = None
        else:
            self.active_layer = previous.name
            self.layer_activation_key = previous.activation_key
            self.layer_used = previous.used
            self.layer_once = previous.mode == 'once'
            self._layer_mode = previous.mode
            self._layer_once_key = previous.one_shot_key
            self._layer_deadline = previous.deadline
            self._momentary_previous = previous.previous
            restored_layer = previous.name
        logger.info(
            'momentary layer released',
            extra=self._context(layer=layer, restored_layer=restored_layer),
        )
        if self.layer_once and self._layer_once_key == released_key:
            self.deactivate_layer()

    def _remove_released_momentary(self, snapshot, released_key):
        if snapshot.mode == 'momentary' and snapshot.activation_key == released_key:
            previous = snapshot.previous
            if (
                previous is not None
                and previous.mode == 'once'
                and previous.one_shot_key == released_key
            ):
                previous = previous.previous
            return previous, True
        if snapshot.previous is None:
            return snapshot, False
        previous, removed = self._remove_released_momentary(snapshot.previous, released_key)
        if not removed:
            return snapshot, False
        return replace(snapshot, previous=previous), True

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
        command_with_args = command.split()
        command = command_with_args[0]
        if command == 'layer':
            layer_name = command_with_args[1]
            mode = command_with_args[2] if len(command_with_args) > 2 else 'persistent'
            self.activate_layer(layer_name, code, mode=mode)
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
