import unittest
from types import SimpleNamespace
from unittest.mock import patch

from macropad.cli import service


class ServiceCommandTests(unittest.TestCase):
    def test_systemctl_actions_preserve_exit_status(self):
        for action in service.SYSTEMCTL_ACTIONS:
            with self.subTest(action=action):
                with patch(
                    'macropad.cli.service.subprocess.run',
                    return_value=SimpleNamespace(returncode=7),
                ) as run_command:
                    exit_status = service.run(action)

                self.assertEqual(7, exit_status)
                run_command.assert_called_once_with(
                    ['systemctl', '--user', action, 'macropad.service'],
                    check=False,
                )

    def test_logs_follow_user_service_journal(self):
        with patch(
            'macropad.cli.service.subprocess.run',
            return_value=SimpleNamespace(returncode=0),
        ) as run_command:
            exit_status = service.run('logs')

        self.assertEqual(0, exit_status)
        run_command.assert_called_once_with(
            ['journalctl', '--user', '-u', 'macropad.service', '-f'],
            check=False,
        )

    def test_unknown_action_is_rejected_without_starting_process(self):
        with (
            patch('macropad.cli.service.subprocess.run') as run_command,
            self.assertRaisesRegex(ValueError, "unsupported service action 'invalid'"),
        ):
            service.run('invalid')

        run_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
