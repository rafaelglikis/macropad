import unittest
from unittest.mock import Mock, patch

from macropad import utils


class CommandProcessTests(unittest.TestCase):
    def setUp(self):
        utils._command_processes.clear()

    def tearDown(self):
        utils._command_processes.clear()

    def test_launched_commands_are_tracked_and_finished_commands_are_reaped(self):
        finished_process = Mock()
        finished_process.poll.return_value = 0
        running_process = Mock()
        running_process.poll.return_value = None

        with patch(
                'macropad.utils.subprocess.Popen',
                side_effect=[finished_process, running_process],
        ):
            utils.daemonize_and_run_command('first-command')
            utils.daemonize_and_run_command('second-command')

        utils.reap_finished_commands()

        self.assertEqual([running_process], utils._command_processes)
        finished_process.poll.assert_called_once_with()
        running_process.poll.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
