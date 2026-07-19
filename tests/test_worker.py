import queue
import signal
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from macropad import worker


class WorkerTests(unittest.TestCase):
    def test_sigterm_handler_requests_worker_shutdown(self):
        shutdown_event = threading.Event()

        with patch('macropad.worker.signal.signal') as install_signal:
            worker.install_shutdown_handler(shutdown_event)

        handler = install_signal.call_args.args[1]
        handler(signal.SIGTERM, None)

        install_signal.assert_called_once_with(signal.SIGTERM, handler)
        self.assertTrue(shutdown_event.is_set())

    def test_run_creates_and_shuts_down_handler_inside_worker(self):
        profile_config = SimpleNamespace(device='Macro Keyboard', keyboard=object())
        shutdown_event = Mock()
        handler = Mock()
        action_executor = Mock()

        with (
            patch('macropad.worker.configure_logging') as configure_logging,
            patch('macropad.worker.notifications.configure') as configure_notifications,
            patch('macropad.worker.install_shutdown_handler') as install_shutdown_handler,
            patch('macropad.worker.ActionExecutor', return_value=action_executor) as executor_type,
            patch('macropad.worker.KeyboardHandler', return_value=handler) as handler_type,
            patch('macropad.worker.interceptor.listen') as listen,
        ):
            worker.run(
                profile_config,
                shutdown_event,
                action_debug=True,
                verbose=True,
                debug=False,
                notifications_enabled=False,
            )

        configure_logging.assert_called_once_with(verbose=True, debug=True)
        configure_notifications.assert_called_once_with(False)
        install_shutdown_handler.assert_called_once_with(shutdown_event)
        executor_type.assert_called_once_with(device='Macro Keyboard', debug_output=True)
        handler_type.assert_called_once_with(
            profile_config.keyboard,
            action_executor=action_executor,
            device='Macro Keyboard',
        )
        listen.assert_called_once_with('Macro Keyboard', handler, shutdown_event)
        handler.shutdown.assert_called_once_with()

    def test_run_shuts_down_handler_after_listener_failure(self):
        profile_config = SimpleNamespace(device='Macro Keyboard', keyboard=object())
        handler = Mock()

        with (
            patch('macropad.worker.configure_logging'),
            patch('macropad.worker.install_shutdown_handler'),
            patch('macropad.worker.KeyboardHandler', return_value=handler),
            patch(
                'macropad.worker.interceptor.listen',
                side_effect=RuntimeError('listener failed'),
            ),
            self.assertRaisesRegex(RuntimeError, 'listener failed'),
        ):
            worker.run(profile_config, Mock())

        handler.shutdown.assert_called_once_with()

    def test_worker_reports_waiting_opening_and_listening_states(self):
        profile_config = SimpleNamespace(device='Macro Keyboard', keyboard=object())
        shutdown_event = Mock()
        shutdown_event.is_set.return_value = False
        status_queue = queue.Queue()

        def listen(device_name, handler, event, status_callback):
            status_callback('opening', ('/dev/input/event12',), None)
            status_callback('listening', ('/dev/input/event12',), None)

        with (
            patch('macropad.worker.configure_logging'),
            patch('macropad.worker.install_shutdown_handler'),
            patch('macropad.worker.ActionExecutor'),
            patch('macropad.worker.KeyboardHandler') as handler_type,
            patch('macropad.worker.interceptor.listen', side_effect=listen),
        ):
            worker.run(
                profile_config,
                shutdown_event,
                status_queue=status_queue,
                worker_id=7,
            )

        updates = [status_queue.get_nowait() for _ in range(3)]
        self.assertEqual(
            ['waiting', 'opening', 'listening'], [update['state'] for update in updates]
        )
        self.assertTrue(all(update['worker_id'] == 7 for update in updates))
        handler_type.return_value.shutdown.assert_called_once_with()

    def test_worker_preserves_path_from_fatal_interceptor_error(self):
        profile_config = SimpleNamespace(device='Macro Keyboard', keyboard=object())
        shutdown_event = Mock()
        shutdown_event.is_set.return_value = False
        status_queue = queue.Queue()
        error = OSError(16, 'device busy')

        def listen(device_name, handler, event, status_callback):
            status_callback('error', ('/dev/input/event12',), str(error))
            raise error

        with (
            patch('macropad.worker.configure_logging'),
            patch('macropad.worker.install_shutdown_handler'),
            patch('macropad.worker.ActionExecutor'),
            patch('macropad.worker.KeyboardHandler'),
            patch('macropad.worker.interceptor.listen', side_effect=listen),
            self.assertRaises(OSError),
        ):
            worker.run(
                profile_config,
                shutdown_event,
                status_queue=status_queue,
                worker_id=8,
            )

        updates = [status_queue.get_nowait() for _ in range(2)]
        self.assertEqual('error', updates[-1]['state'])
        self.assertEqual(('/dev/input/event12',), updates[-1]['paths'])


if __name__ == '__main__':
    unittest.main()
