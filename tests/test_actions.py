import subprocess
import unittest
from unittest.mock import Mock, patch

from macropad.actions import ActionExecutor


class ActionExecutorTests(unittest.TestCase):
    def test_submit_starts_detached_shell_command(self):
        process = Mock()
        process_factory = Mock(return_value=process)
        executor = ActionExecutor(process_factory=process_factory)

        submitted = executor.submit('demo-command')

        self.assertTrue(submitted)
        self.assertEqual(1, executor.active_count)
        process_factory.assert_called_once_with(
            'demo-command',
            shell=True,
            cwd='/',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    def test_submit_rejects_command_at_concurrency_limit(self):
        processes = [Mock(), Mock()]
        for process in processes:
            process.poll.return_value = None
        process_factory = Mock(side_effect=processes)
        executor = ActionExecutor(max_concurrent=2, process_factory=process_factory)

        self.assertTrue(executor.submit('first-command'))
        self.assertTrue(executor.submit('second-command'))
        with patch('macropad.actions.logger') as logger:
            submitted = executor.submit('rejected-command')

        self.assertFalse(submitted)
        self.assertEqual(2, executor.active_count)
        self.assertEqual(2, process_factory.call_count)
        logger.warning.assert_called_once_with(
            'action rejected at concurrency limit',
            extra={'command': 'rejected-command', 'limit': 2},
        )

    def test_tick_reaps_commands_and_reports_exit_status(self):
        successful_process = Mock()
        failed_process = Mock()
        running_process = Mock()
        for process in (successful_process, failed_process, running_process):
            process.poll.return_value = None
        executor = ActionExecutor(
            process_factory=Mock(side_effect=[successful_process, failed_process, running_process])
        )
        executor.submit('successful-command')
        executor.submit('failed-command')
        executor.submit('running-command')
        successful_process.poll.return_value = 0
        failed_process.poll.return_value = 7

        successful_process.pid = 100
        failed_process.pid = 101
        with patch('macropad.actions.logger') as logger:
            executor.tick()

        self.assertEqual(1, executor.active_count)
        logger.info.assert_called_once_with(
            'action exited',
            extra={
                'command': 'successful-command',
                'pid': 100,
                'exit_status': 0,
            },
        )
        logger.warning.assert_called_once_with(
            'action exited',
            extra={
                'command': 'failed-command',
                'pid': 101,
                'exit_status': 7,
            },
        )

    def test_submit_reports_process_start_failure(self):
        executor = ActionExecutor(process_factory=Mock(side_effect=OSError('cannot start process')))

        with patch('macropad.actions.logger') as logger:
            submitted = executor.submit('broken-command')

        self.assertFalse(submitted)
        self.assertEqual(0, executor.active_count)
        logger.error.assert_called_once_with(
            'action failed to start',
            extra={
                'command': 'broken-command',
                'error': 'cannot start process',
            },
        )

    def test_shutdown_detaches_running_commands(self):
        process = Mock()
        process.poll.return_value = None
        executor = ActionExecutor(process_factory=Mock(return_value=process))
        executor.submit('long-command')

        with patch('macropad.actions.logger') as logger:
            executor.shutdown()

        self.assertEqual(0, executor.active_count)
        logger.info.assert_called_once_with(
            'detaching running actions during worker shutdown',
            extra={'count': 1},
        )


if __name__ == '__main__':
    unittest.main()
