import unittest
from types import SimpleNamespace
from unittest.mock import patch

from macropad.cli import service


class ServiceCommandTests(unittest.TestCase):
    def test_service_info_is_read_from_systemd(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout=(
                'ActiveState=active\n'
                'FragmentPath=/home/demo/.config/systemd/user/macropad.service\n'
                'Environment=PYTHONUNBUFFERED=1 PATH=/home/demo/bin:/usr/bin\n'
            ),
        )

        with patch('macropad.cli.service.subprocess.run', return_value=completed) as run_command:
            service_info = service.get_info()

        self.assertEqual(
            service.ServiceInfo(
                '/home/demo/.config/systemd/user/macropad.service',
                True,
                action_path='/home/demo/bin:/usr/bin',
            ),
            service_info,
        )
        run_command.assert_called_once_with(
            [
                'systemctl',
                '--user',
                'show',
                'macropad.service',
                '--property=FragmentPath',
                '--property=ActiveState',
                '--property=Environment',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

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
