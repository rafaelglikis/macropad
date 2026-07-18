import unittest
from unittest.mock import Mock, call, patch

from evdev import InputEvent, ecodes

from macropad import profiles
from macropad.handlers import KeyboardHandler


class FakeClock:
    def __init__(self):
        self.current_time = 0.0

    def __call__(self):
        return self.current_time

    def advance(self, seconds):
        self.current_time += seconds


class KeyboardHandlerLayerTests(unittest.TestCase):
    def setUp(self):
        self.send_notification = patch('macropad.notifications.send').start()
        self.addCleanup(patch.stopall)
        self.clock = FakeClock()
        self.action_executor = Mock()
        self.run_command = self.action_executor.submit

    @staticmethod
    def _keyboard_config(bindings):
        return profiles.validate_profile_data(
            {
                'device': 'Test Device',
                'version': 1,
                'bindings': bindings,
            }
        ).keyboard

    def _create_handler(self, layer_binding):
        return KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': {'up': '^layer mod once'},
                    'KEY_T': {
                        'up': 'base-command',
                        'layers': {
                            'mod': layer_binding,
                        },
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

    @staticmethod
    def _event(code, value):
        return InputEvent(0, 0, ecodes.EV_KEY, code, value)

    def _activate_layer(self, handler):
        handler.handle(self._event(ecodes.KEY_SPACE, 1))
        handler.handle(self._event(ecodes.KEY_SPACE, 0))
        self.assertEqual('mod', handler.active_layer)

    def _advance(self, handler, seconds):
        self.clock.advance(seconds)
        handler.tick()

    def test_one_shot_up_binding_stays_active_until_key_release(self):
        handler = self._create_handler({'up': ['layer-command-1', 'layer-command-2']})
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))

        self.assertEqual('mod', handler.active_layer)
        self.run_command.assert_not_called()

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.assertEqual(
            [call('layer-command-1'), call('layer-command-2')],
            self.run_command.call_args_list,
        )
        self.assertIsNone(handler.active_layer)

    def test_action_submission_logs_device_key_and_event_context(self):
        handler = KeyboardHandler(
            self._keyboard_config({'KEY_A': {'up': 'a-command'}}),
            clock=self.clock,
            action_executor=self.action_executor,
            device='Test Device',
        )

        with patch('macropad.handlers.logger') as logger:
            handler.handle(self._event(ecodes.KEY_A, 0))

        logger.info.assert_called_once_with(
            'submitting action',
            extra={
                'key': 'KEY_A',
                'event': 'up',
                'command': 'a-command',
                'device': 'Test Device',
            },
        )
        self.run_command.assert_called_once_with('a-command')

    def test_one_shot_down_binding_does_not_fall_through_on_release(self):
        handler = self._create_handler({'down': 'layer-command'})
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))

        self.run_command.assert_called_once_with('layer-command')
        self.assertEqual('mod', handler.active_layer)

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.run_command.assert_called_once_with('layer-command')
        self.assertIsNone(handler.active_layer)

    def test_stale_debounced_event_does_not_affect_reactivated_layer(self):
        handler = self._create_handler(
            {
                'up': 'layer-up-command',
                'hold': 'layer-hold-command',
            }
        )
        self._activate_layer(handler)
        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))

        handler.deactivate_layer()
        handler.activate_layer('mod', 'KEY_SPACE')
        self._advance(handler, 0.3)

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

    def test_previous_timeout_does_not_deactivate_reactivated_layer(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        handler.activate_layer('mod', 'KEY_SPACE')
        self._advance(handler, 0.1)

        self.assertEqual('mod', handler.active_layer)

    def test_one_shot_layer_deactivates_when_deadline_passes(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        self._advance(handler, 0.04)
        self.assertEqual('mod', handler.active_layer)

        self._advance(handler, 0.02)
        self.assertIsNone(handler.active_layer)

    def test_one_shot_hold_binding_deactivates_after_debounced_release(self):
        handler = self._create_handler(
            {
                'up': 'layer-up-command',
                'hold': 'layer-hold-command',
            }
        )
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 2))
        handler.handle(self._event(ecodes.KEY_T, 0))
        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with('layer-hold-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_layer_supports_debounced_double_tap(self):
        handler = self._create_handler(
            {
                'up': 'layer-up-command',
                'double_tap': 'layer-double-tap-command',
            }
        )
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))
        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))
        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with('layer-double-tap-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_layer_supports_double_tap_only_binding(self):
        handler = self._create_handler(
            {
                'double_tap': 'layer-double-tap-command',
            }
        )
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))
        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with('layer-double-tap-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_layer_supports_triple_tap_only_binding(self):
        handler = self._create_handler(
            {
                'triple_tap': 'layer-triple-tap-command',
            }
        )
        self._activate_layer(handler)

        for _ in range(3):
            handler.handle(self._event(ecodes.KEY_T, 1))
            handler.handle(self._event(ecodes.KEY_T, 0))

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with('layer-triple-tap-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_timeout_is_cancelled_while_key_is_in_progress(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        handler.handle(self._event(ecodes.KEY_T, 1))
        self._advance(handler, 0.1)

        self.assertEqual('mod', handler.active_layer)

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.run_command.assert_called_once_with('layer-command')
        self.assertIsNone(handler.active_layer)

    def test_debounce_is_independent_for_each_key(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'a-command',
                        'double_tap': 'a-double-tap-command',
                    },
                    'KEY_B': {
                        'up': 'b-command',
                        'double_tap': 'b-double-tap-command',
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))
        handler.handle(self._event(ecodes.KEY_B, 1))
        handler.handle(self._event(ecodes.KEY_B, 0))
        self.run_command.assert_not_called()

        self._advance(handler, 0.3)

        self.assertCountEqual(
            [call('a-command'), call('b-command')],
            self.run_command.call_args_list,
        )

    def test_debounce_deadline_moves_to_latest_event(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'a-command',
                        'double_tap': 'a-double-tap-command',
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        self._advance(handler, 0.15)
        handler.handle(self._event(ecodes.KEY_A, 0))
        self._advance(handler, 0.1)

        self.run_command.assert_not_called()

        self._advance(handler, 0.11)
        self.run_command.assert_called_once_with('a-command')

    def test_tap_history_is_independent_for_each_key(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'a-command',
                        'double_tap': 'a-double-tap-command',
                    },
                    'KEY_B': {
                        'up': 'b-command',
                        'double_tap': 'b-double-tap-command',
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        for _ in range(2):
            handler.handle(self._event(ecodes.KEY_A, 1))
            handler.handle(self._event(ecodes.KEY_A, 0))
            handler.handle(self._event(ecodes.KEY_B, 1))
            handler.handle(self._event(ecodes.KEY_B, 0))
        self._advance(handler, 0.3)

        self.assertCountEqual(
            [call('a-double-tap-command'), call('b-double-tap-command')],
            self.run_command.call_args_list,
        )

    def test_down_only_binding_repeats_for_key_hold_events(self):
        handler = KeyboardHandler(
            self._keyboard_config({'KEY_A': {'down': 'repeat-command'}}),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 2))
        handler.handle(self._event(ecodes.KEY_A, 2))
        handler.handle(self._event(ecodes.KEY_A, 0))

        self.assertEqual(
            [call('repeat-command')] * 3,
            self.run_command.call_args_list,
        )

    def test_hold_binding_fires_once_without_corrupting_next_tap(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'up-command',
                        'hold': 'hold-command',
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 2))
        handler.handle(self._event(ecodes.KEY_A, 2))
        handler.handle(self._event(ecodes.KEY_A, 0))
        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with('hold-command')

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))
        self._advance(handler, 0.3)

        self.assertEqual(
            [call('hold-command'), call('up-command')],
            self.run_command.call_args_list,
        )


if __name__ == '__main__':
    unittest.main()
