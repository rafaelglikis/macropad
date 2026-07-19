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
            )

        configure_logging.assert_called_once_with(verbose=True, debug=True)
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


if __name__ == '__main__':
    unittest.main()
