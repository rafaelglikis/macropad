import time
import unittest
from unittest.mock import call, patch

from evdev import InputEvent, ecodes

from handlers import KeyboardHandler


class KeyboardHandlerLayerTests(unittest.TestCase):
    def setUp(self):
        self.run_command = patch('utils.daemonize_and_run_command').start()
        self.send_notification = patch('utils.send_notification').start()
        self.addCleanup(patch.stopall)
        self.handlers = []
        self.addCleanup(self._cancel_handler_timers)

    def _cancel_handler_timers(self):
        for handler in self.handlers:
            handler._cancel_layer_timer()

    def _create_handler(self, layer_binding):
        handler = KeyboardHandler({
            'bindings': {
                'KEY_SPACE': {'up': '^layer mod once'},
                'KEY_T': {
                    'up': 'base-command',
                    'layers': {
                        'mod': layer_binding,
                    },
                },
            },
        })
        self.handlers.append(handler)
        return handler

    @staticmethod
    def _event(code, value):
        return InputEvent(0, 0, ecodes.EV_KEY, code, value)

    def _activate_layer(self, handler):
        handler.handle(self._event(ecodes.KEY_SPACE, 1))
        handler.handle(self._event(ecodes.KEY_SPACE, 0))
        self.assertEqual('mod', handler.active_layer)

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
        handler = self._create_handler({
            'up': 'layer-up-command',
            'hold': 'layer-hold-command',
        })
        self._activate_layer(handler)
        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))

        handler.deactivate_layer()
        handler.activate_layer('mod', 'KEY_SPACE')
        time.sleep(0.3)

        self.run_command.assert_not_called()
        self.assertEqual('mod', handler.active_layer)

    def test_previous_timeout_does_not_deactivate_reactivated_layer(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        handler.activate_layer('mod', 'KEY_SPACE')
        time.sleep(0.1)

        self.assertEqual('mod', handler.active_layer)

    def test_one_shot_hold_binding_deactivates_after_debounced_release(self):
        handler = self._create_handler({
            'up': 'layer-up-command',
            'hold': 'layer-hold-command',
        })
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 2))
        handler.handle(self._event(ecodes.KEY_T, 0))
        time.sleep(0.3)

        self.run_command.assert_called_once_with('layer-hold-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_layer_supports_debounced_double_tap(self):
        handler = self._create_handler({
            'up': 'layer-up-command',
            'double_tap': 'layer-double-tap-command',
        })
        self._activate_layer(handler)

        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))
        handler.handle(self._event(ecodes.KEY_T, 1))
        handler.handle(self._event(ecodes.KEY_T, 0))
        time.sleep(0.3)

        self.run_command.assert_called_once_with('layer-double-tap-command')
        self.assertIsNone(handler.active_layer)

    def test_one_shot_timeout_is_cancelled_while_key_is_in_progress(self):
        handler = self._create_handler({'up': 'layer-command'})
        handler.activate_layer('mod', 'KEY_SPACE', once=True, deactivate_after=0.05)

        handler.handle(self._event(ecodes.KEY_T, 1))
        time.sleep(0.1)

        self.assertEqual('mod', handler.active_layer)

        handler.handle(self._event(ecodes.KEY_T, 0))

        self.run_command.assert_called_once_with('layer-command')
        self.assertIsNone(handler.active_layer)


if __name__ == '__main__':
    unittest.main()
