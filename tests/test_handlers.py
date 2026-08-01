import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

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
    def _keyboard_config(bindings, timing=None, layers=None, context=None):
        profile_data = {
            'device': 'Test Device',
            'version': 1,
            'bindings': bindings,
        }
        if timing is not None:
            profile_data['timing'] = timing
        if layers is not None:
            profile_data['layers'] = layers
        if context is not None:
            profile_data['context'] = context
        return profiles.validate_profile_data(profile_data).keyboard

    def _create_handler(self, layer_binding, timing=None):
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
                },
                timing,
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

    def _tap(self, handler, key_code):
        handler.handle(self._event(key_code, 1))
        handler.handle(self._event(key_code, 0))

    def assert_submitted_commands(self, *commands):
        self.assertEqual(
            list(commands),
            [submission.args[0] for submission in self.run_command.call_args_list],
        )

    def test_one_shot_up_binding_stays_active_until_key_release(self):
        handler = self._create_handler({'up': ['layer-command-1', 'layer-command-2']})
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))

        self.assertEqual('mod', handler.active_layer)
        self.run_command.assert_not_called()

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.assert_submitted_commands('layer-command-1', 'layer-command-2')
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
                'layer': 'base',
                'device': 'Test Device',
            },
        )
        self.run_command.assert_called_once_with(
            'a-command',
            key='KEY_A',
            event='up',
            layer='base',
        )

    def test_context_layer_is_selected_on_press_and_latched_until_release(self):
        context_resolver = Mock(side_effect=['org.kde.konsole', 'jetbrains-phpstorm'])
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_A': 'base-command'},
                layers={
                    'konsole': {'bindings': {'KEY_A': 'konsole-command'}},
                    'phpstorm': {'bindings': {'KEY_A': 'phpstorm-command'}},
                },
                context={
                    'command': 'active-window-class',
                    'layers': {
                        'org.kde.konsole': 'konsole',
                        'jetbrains-phpstorm': 'phpstorm',
                    },
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
            context_resolver=context_resolver,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))
        self.assert_submitted_commands('konsole-command')
        context_resolver.assert_called_once_with('active-window-class')

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('konsole-command', 'phpstorm-command')
        self.assertEqual(2, context_resolver.call_count)

    def test_manual_layer_takes_priority_over_context_layer(self):
        context_resolver = Mock(return_value='org.kde.konsole')
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer manual',
                    'KEY_A': 'base-command',
                },
                layers={
                    'manual': {'bindings': {'KEY_A': 'manual-command'}},
                    'konsole': {'bindings': {'KEY_A': 'konsole-command'}},
                },
                context={
                    'command': 'active-window-class',
                    'layers': {'org.kde.konsole': 'konsole'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
            context_resolver=context_resolver,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('manual-command')

    def test_manual_layer_falls_back_to_context_layer_before_base(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer manual',
                    'KEY_A': 'base-command',
                },
                layers={
                    'manual': {'fallback': 'base'},
                    'konsole': {'bindings': {'KEY_A': 'konsole-command'}},
                },
                context={
                    'command': 'active-window-class',
                    'layers': {'org.kde.konsole': 'konsole'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
            context_resolver=Mock(return_value='org.kde.konsole'),
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('konsole-command')

    def test_unknown_context_falls_back_to_base_binding(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_A': 'base-command'},
                layers={'konsole': {'bindings': {'KEY_A': 'konsole-command'}}},
                context={
                    'command': 'active-window-class',
                    'layers': {'org.kde.konsole': 'konsole'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
            context_resolver=Mock(return_value='unknown-app'),
        )

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('base-command')

    def test_context_command_output_selects_layer_with_bounded_lookup(self):
        start_context_command = patch('macropad.handlers.subprocess.Popen').start()
        process = start_context_command.return_value
        process.communicate.return_value = ('org.kde.konsole\n', '')
        process.returncode = 0
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_A': 'base-command'},
                layers={'konsole': {'bindings': {'KEY_A': 'konsole-command'}}},
                context={
                    'command': 'active-window-class',
                    'layers': {'org.kde.konsole': 'konsole'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('konsole-command')
        start_context_command.assert_called_once_with(
            'active-window-class',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            start_new_session=True,
        )
        process.communicate.assert_called_once_with(timeout=0.1)

    def test_context_command_timeout_kills_process_group_and_falls_back(self):
        start_context_command = patch('macropad.handlers.subprocess.Popen').start()
        kill_process_group = patch('macropad.handlers.os.killpg').start()
        process = start_context_command.return_value
        process.pid = 42
        process.communicate.side_effect = subprocess.TimeoutExpired('active-window-class', 0.1)
        process.wait.side_effect = subprocess.TimeoutExpired('active-window-class', 0.1)
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_A': 'base-command'},
                layers={'konsole': {'bindings': {'KEY_A': 'konsole-command'}}},
                context={
                    'command': 'active-window-class',
                    'layers': {'org.kde.konsole': 'konsole'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        with self.assertLogs('macropad.handlers', level='WARNING'):
            self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('base-command')
        kill_process_group.assert_called_once_with(42, signal.SIGKILL)
        process.stdout.close.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=0.1)
        process.communicate.assert_called_once_with(timeout=0.1)

    def test_active_layer_falls_back_to_base_binding_by_default(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer mod',
                    'KEY_A': 'base-command',
                },
                layers={'mod': {'fallback': 'base'}},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.run_command.assert_called_once_with(
            'base-command',
            key='KEY_A',
            event='up',
            layer='base',
        )
        self.assertEqual('mod', handler.active_layer)

    def test_layer_can_disable_base_fallback(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer mod',
                    'KEY_A': 'base-command',
                },
                layers={'mod': {'fallback': 'none'}},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

    def test_base_fallback_consumes_one_shot_layer(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer mod once',
                    'KEY_A': 'base-command',
                },
                layers={'mod': {'fallback': 'base'}},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.assert_submitted_commands('base-command')
        self.assertIsNone(handler.active_layer)

    def test_fallback_disabled_key_does_not_consume_one_shot_layer(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer mod once',
                    'KEY_A': 'base-command',
                },
                layers={'mod': {'fallback': 'none'}},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        self._tap(handler, ecodes.KEY_A)

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

    def test_toggle_activation_key_turns_off_fallback_disabled_layer(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_SPACE': '^layer mod toggle'},
                layers={'mod': {'fallback': 'none'}},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        self._tap(handler, ecodes.KEY_SPACE)
        self.assertEqual('mod', handler.active_layer)
        self._tap(handler, ecodes.KEY_SPACE)

        self.assertIsNone(handler.active_layer)
        self.assertEqual(2, self.send_notification.call_count)

    def test_momentary_layer_restores_previous_layer_without_notifications(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_P': '^layer persistent',
                    'KEY_SPACE': {'down': '^layer mod momentary'},
                },
                layers={
                    'persistent': {'fallback': 'base'},
                    'mod': {'fallback': 'base'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_P)
        self.send_notification.reset_mock()

        handler.handle(self._event(ecodes.KEY_SPACE, 1))
        handler.handle(self._event(ecodes.KEY_SPACE, 2))
        self.assertEqual('mod', handler.active_layer)
        handler.handle(self._event(ecodes.KEY_SPACE, 0))

        self.assertEqual('persistent', handler.active_layer)
        self.send_notification.assert_not_called()

    def test_momentary_release_completes_previous_one_shot_claim(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': '^layer mod once',
                    'KEY_A': {'down': '^layer navigation momentary'},
                },
                layers={
                    'mod': {'fallback': 'base'},
                    'navigation': {'fallback': 'base'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        self._tap(handler, ecodes.KEY_SPACE)

        handler.handle(self._event(ecodes.KEY_A, 1))
        self.assertEqual('navigation', handler.active_layer)
        handler.handle(self._event(ecodes.KEY_A, 0))

        self.assertIsNone(handler.active_layer)

    def test_nested_momentary_release_skips_layer_whose_key_was_released(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {'down': '^layer mod momentary'},
                    'KEY_B': {'down': '^layer navigation momentary'},
                },
                layers={
                    'mod': {
                        'bindings': {
                            'KEY_B': {'down': '^layer navigation momentary'},
                        }
                    },
                    'navigation': {'fallback': 'base'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_B, 1))
        self.assertEqual('navigation', handler.active_layer)
        handler.handle(self._event(ecodes.KEY_A, 0))
        handler.handle(self._event(ecodes.KEY_B, 0))

        self.assertIsNone(handler.active_layer)
        self.send_notification.assert_not_called()

    def test_later_toggle_transition_supersedes_momentary_restoration(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_SPACE': {'down': '^layer mod momentary'},
                    'KEY_T': '^layer navigation toggle',
                },
                layers={
                    'mod': {
                        'bindings': {
                            'KEY_T': '^layer navigation toggle',
                        }
                    },
                    'navigation': {'fallback': 'none'},
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_SPACE, 1))
        self._tap(handler, ecodes.KEY_T)
        handler.handle(self._event(ecodes.KEY_SPACE, 0))

        self.assertEqual('navigation', handler.active_layer)

    def test_momentary_release_invalidates_delayed_layer_action(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {'KEY_SPACE': {'down': '^layer mod momentary'}},
                layers={
                    'mod': {
                        'fallback': 'none',
                        'bindings': {
                            'KEY_T': {
                                'up': 'layer-command',
                                'double_tap': 'layer-double-command',
                            }
                        },
                    }
                },
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )

        handler.handle(self._event(ecodes.KEY_SPACE, 1))
        self._tap(handler, ecodes.KEY_T)
        handler.handle(self._event(ecodes.KEY_SPACE, 0))
        self._advance(handler, 0.3)

        self.run_command.assert_not_called()
        self.assertIsNone(handler.active_layer)

    def test_delayed_base_action_keeps_base_layer_context_after_layer_activation(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'a-command',
                        'double_tap': 'double-a-command',
                    },
                    'KEY_SPACE': {'up': '^layer mod'},
                    'KEY_T': {
                        'up': 'base-command',
                        'layers': {'mod': {'up': 'layer-command'}},
                    },
                }
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))

        handler.activate_layer('mod', 'KEY_SPACE')
        self._advance(handler, 0.3)

        self.run_command.assert_called_once_with(
            'a-command',
            key='KEY_A',
            event='up',
            layer='base',
        )

    def test_one_shot_down_binding_does_not_fall_through_on_release(self):
        handler = self._create_handler({'down': 'layer-command'})
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))

        self.assert_submitted_commands('layer-command')
        self.assertEqual('mod', handler.active_layer)

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.assert_submitted_commands('layer-command')
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

    def test_default_one_shot_timeout_preserves_existing_behavior(self):
        handler = self._create_handler({'up': 'layer-command'})
        self._activate_layer(handler)

        self._advance(handler, 4.9)
        self.assertEqual('mod', handler.active_layer)

        self._advance(handler, 0.2)
        self.assertIsNone(handler.active_layer)

    def test_configured_one_shot_timeout_controls_layer_deadline(self):
        handler = self._create_handler(
            {'up': 'layer-command'},
            timing={'one_shot_timeout_ms': 50},
        )
        self._activate_layer(handler)

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

        self.assert_submitted_commands('layer-hold-command')
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

        self.assert_submitted_commands('layer-double-tap-command')
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

        self.assert_submitted_commands('layer-double-tap-command')
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

        self.assert_submitted_commands('layer-triple-tap-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_timeout_is_cancelled_while_key_is_in_progress(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        handler.handle(self._event(ecodes.KEY_T, 1))
        self._advance(handler, 0.1)

        self.assertEqual('mod', handler.active_layer)

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.assert_submitted_commands('layer-command')
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
            ['a-command', 'b-command'],
            [submission.args[0] for submission in self.run_command.call_args_list],
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
        self.assert_submitted_commands('a-command')

    def test_configured_multi_tap_window_controls_resolution_deadline(self):
        handler = KeyboardHandler(
            self._keyboard_config(
                {
                    'KEY_A': {
                        'up': 'a-command',
                        'double_tap': 'a-double-tap-command',
                    },
                },
                timing={'multi_tap_ms': 500},
            ),
            clock=self.clock,
            action_executor=self.action_executor,
        )
        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))

        self._advance(handler, 0.3)
        self.run_command.assert_not_called()

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))
        self._advance(handler, 0.49)
        self.run_command.assert_not_called()

        self._advance(handler, 0.02)
        self.assert_submitted_commands('a-double-tap-command')

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
            ['a-double-tap-command', 'b-double-tap-command'],
            [submission.args[0] for submission in self.run_command.call_args_list],
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

        self.assert_submitted_commands(*(['repeat-command'] * 3))

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

        self.assert_submitted_commands('hold-command')

        handler.handle(self._event(ecodes.KEY_A, 1))
        handler.handle(self._event(ecodes.KEY_A, 0))
        self._advance(handler, 0.3)

        self.assert_submitted_commands('hold-command', 'up-command')


if __name__ == '__main__':
    unittest.main()
