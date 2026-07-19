import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from macropad import service_unit
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

    def test_install_writes_unit_reloads_and_enables_now(self):
        executable = Path('/tools/macropad/bin/macropad')
        unit_path = Path('/home/demo/.config/systemd/user/macropad.service')

        with (
            patch('macropad.cli.service.service_unit.resolve_executable', return_value=executable),
            patch('macropad.cli.service.service_unit.resolve_unit_path', return_value=unit_path),
            patch(
                'macropad.cli.service.get_info',
                return_value=service.ServiceInfo(None, False),
            ),
            patch('macropad.cli.service.service_unit.install_unit') as install_unit,
            patch('macropad.cli.service._run_systemctl', side_effect=[0, 0, 0]) as run_systemctl,
            redirect_stdout(io.StringIO()),
        ):
            exit_status = service.run('install', force=True)

        self.assertEqual(0, exit_status)
        install_unit.assert_called_once_with(
            unit_path,
            service_unit.render_unit(executable),
            force=True,
        )
        self.assertEqual(
            [
                call('daemon-reload'),
                call('enable', service.SERVICE_NAME),
                call('start', service.SERVICE_NAME),
            ],
            run_systemctl.call_args_list,
        )

    def test_install_refuses_unrecognized_unit_loaded_from_another_path(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            loaded_path = Path(temp_directory) / 'system/macropad.service'
            loaded_path.parent.mkdir()
            loaded_path.write_text('[Unit]\nDescription=Unrelated\n', encoding='utf-8')
            unit_path = Path(temp_directory) / 'user/macropad.service'

            with (
                patch(
                    'macropad.cli.service.service_unit.resolve_executable',
                    return_value=Path('/tools/macropad/bin/macropad'),
                ),
                patch(
                    'macropad.cli.service.service_unit.resolve_unit_path', return_value=unit_path
                ),
                patch(
                    'macropad.cli.service.get_info',
                    return_value=service.ServiceInfo(str(loaded_path), False),
                ),
                patch('macropad.cli.service.service_unit.install_unit') as install_unit,
                patch('macropad.cli.service._run_systemctl') as run_systemctl,
                redirect_stdout(io.StringIO()),
            ):
                exit_status = service.run('install')

        self.assertEqual(1, exit_status)
        install_unit.assert_not_called()
        run_systemctl.assert_not_called()

    def test_uninstall_disables_before_removing_generated_unit(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            unit_path = Path(temp_directory) / 'macropad.service'
            unit_path.write_text(
                f'{service_unit.GENERATED_MARKER}\nunit',
                encoding='utf-8',
            )

            with (
                patch(
                    'macropad.cli.service.service_unit.resolve_unit_path', return_value=unit_path
                ),
                patch(
                    'macropad.cli.service._run_systemctl', side_effect=[0, 0, 0]
                ) as run_systemctl,
                redirect_stdout(io.StringIO()),
            ):
                exit_status = service.run('uninstall')

            self.assertEqual(0, exit_status)
            self.assertFalse(unit_path.exists())
            self.assertEqual(
                [
                    call('stop', service.SERVICE_NAME),
                    call('disable', service.SERVICE_NAME),
                    call('daemon-reload'),
                ],
                run_systemctl.call_args_list,
            )

    def test_uninstall_refuses_unknown_unit_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            unit_path = Path(temp_directory) / 'macropad.service'
            unit_path.write_text('[Unit]\nDescription=Custom\n', encoding='utf-8')

            with (
                patch(
                    'macropad.cli.service.service_unit.resolve_unit_path', return_value=unit_path
                ),
                patch('macropad.cli.service._run_systemctl') as run_systemctl,
                redirect_stdout(io.StringIO()),
            ):
                exit_status = service.run('uninstall')

            self.assertEqual(1, exit_status)
            self.assertTrue(unit_path.exists())
            run_systemctl.assert_not_called()

    def test_unknown_action_is_rejected_without_starting_process(self):
        with (
            patch('macropad.cli.service.subprocess.run') as run_command,
            self.assertRaisesRegex(ValueError, "unsupported service action 'invalid'"),
        ):
            service.run('invalid')

        run_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
