import errno
import io
import pathlib
import queue
import runpy
import signal
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from macropad import __version__, cli, profile_watcher
from macropad.cli import listen, profile_files
from macropad.cli import validate as validate_command


class ProfileReloadTests(unittest.TestCase):
    def test_success_notification_uses_supervisor_worker_count(self):
        profile_supervisor = SimpleNamespace(
            workers={'first': object(), 'second': object()},
            reload=Mock(),
        )
        args = SimpleNamespace()

        with (
            patch(
                'macropad.cli.listen.profile_files.get_profile_paths',
                return_value=['/profiles/macros.yml'],
            ),
            patch('macropad.cli.listen.notifications.send') as send_notification,
            patch('macropad.cli.listen.logger') as logger,
        ):
            succeeded = listen.reload_profiles(
                profile_supervisor,
                args,
                ['/profiles/changed.yml'],
            )

        self.assertTrue(succeeded)
        self.assertIsNone(profile_supervisor.configuration_error)
        profile_supervisor.reload.assert_called_once_with(['/profiles/macros.yml'])
        send_notification.assert_called_once_with(
            title='Macropad Configuration Updated',
            message='Successfully reloaded 2 profile(s)',
        )
        self.assertEqual(
            [
                call(
                    'reloading profiles',
                    extra={'changed_paths': ('/profiles/changed.yml',)},
                ),
                call(
                    'profiles reloaded',
                    extra={
                        'count': 2,
                        'changed_paths': ('/profiles/changed.yml',),
                    },
                ),
            ],
            logger.info.call_args_list,
        )

    def test_failed_reload_reports_candidate_and_changed_paths(self):
        current_worker = object()
        profile_supervisor = SimpleNamespace(
            workers={'current': current_worker},
            reload=Mock(side_effect=ValueError('invalid binding')),
        )
        args = SimpleNamespace()

        with (
            patch(
                'macropad.cli.listen.profile_files.get_profile_paths',
                return_value=['/profiles/macros.yml'],
            ),
            patch('macropad.cli.listen.notifications.send'),
            patch('macropad.cli.listen.logger') as logger,
        ):
            succeeded = listen.reload_profiles(
                profile_supervisor,
                args,
                ['/profiles/changed.yml'],
            )

        self.assertFalse(succeeded)
        self.assertEqual('invalid binding', profile_supervisor.configuration_error)
        self.assertIs(current_worker, profile_supervisor.workers['current'])
        logger.error.assert_called_once_with(
            'profile reload failed',
            extra={
                'profiles': ('/profiles/macros.yml',),
                'changed_paths': ('/profiles/changed.yml',),
                'error': 'invalid binding',
            },
        )


class ProfilePathTests(unittest.TestCase):
    def test_explicit_and_directory_paths_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            profile_directory = pathlib.Path(temp_directory)
            profile_path = profile_directory / 'macros.yml'
            profile_path.write_text('profile')
            args = SimpleNamespace(
                profile_paths=[str(profile_path)],
                profile_directories=[str(profile_directory)],
            )

            profile_paths = profile_files.get_profile_paths(args)

        self.assertEqual([str(profile_path)], profile_paths)


class ProfileValidationCommandTests(unittest.TestCase):
    def test_validate_resolves_profile_paths_and_runs_validation(self):
        args = SimpleNamespace(
            profile_paths=['/profiles/first.yml'],
            profile_directories=['/profiles/fragments'],
        )
        profile_paths = ['/profiles/first.yml', '/profiles/fragments/second.yml']

        with (
            patch(
                'macropad.cli.validate.profile_files.get_profile_paths',
                return_value=profile_paths,
            ),
            patch('macropad.cli.validate.validation.run', return_value=0) as run_validation,
        ):
            exit_status = validate_command.run(args)

        self.assertEqual(0, exit_status)
        run_validation.assert_called_once_with(profile_paths)

    def test_validate_uses_default_directory_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            default_config_directory = pathlib.Path(temp_directory) / 'profiles'
            args = SimpleNamespace(profile_paths=[], profile_directories=None)

            with (
                patch.object(
                    profile_files,
                    'DEFAULT_CONFIG_DIR',
                    default_config_directory,
                ),
                patch('macropad.cli.profile_files.logger'),
            ):
                exit_status = validate_command.run(args)

        self.assertEqual(1, exit_status)
        self.assertEqual([str(default_config_directory)], args.profile_directories)
        self.assertFalse(default_config_directory.exists())

    def test_validate_arguments_support_files_and_directories(self):
        with patch(
            'sys.argv',
            ['macropad', 'validate', 'primary.yml', '-d', 'fragments', '-d', 'more'],
        ):
            args = cli.parse_args()

        self.assertEqual('validate', args.subcommand)
        self.assertEqual(['primary.yml'], args.profile_paths)
        self.assertEqual(['fragments', 'more'], args.profile_directories)

    def test_main_dispatches_validate_command(self):
        args = SimpleNamespace(subcommand='validate')

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.validate.run', return_value=0) as run_validate,
        ):
            exit_status = cli.main()

        self.assertEqual(0, exit_status)
        run_validate.assert_called_once_with(args)


class ServiceCommandTests(unittest.TestCase):
    def test_service_actions_are_available_as_nested_commands(self):
        for action in cli.service.SERVICE_ACTIONS:
            with self.subTest(action=action):
                with patch('sys.argv', ['macropad', 'service', action]):
                    args = cli.parse_args()

                self.assertEqual('service', args.subcommand)
                self.assertEqual(action, args.service_action)

    def test_service_install_accepts_force(self):
        with patch('sys.argv', ['macropad', 'service', 'install', '--force']):
            args = cli.parse_args()

        self.assertEqual('install', args.service_action)
        self.assertTrue(args.force)

    def test_main_dispatches_service_action(self):
        args = SimpleNamespace(subcommand='service', service_action='restart')

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.service.run', return_value=7) as run_service,
        ):
            exit_status = cli.main()

        self.assertEqual(7, exit_status)
        run_service.assert_called_once_with('restart', force=False)


class GlobalLoggingArgumentTests(unittest.TestCase):
    def test_version_is_available_without_a_subcommand(self):
        output = io.StringIO()

        with (
            patch('sys.argv', ['macropad', '--version']),
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.parse_args()

        self.assertEqual(0, raised.exception.code)
        self.assertEqual(f'macropad {__version__}\n', output.getvalue())

    def test_global_logging_arguments(self):
        with patch('sys.argv', ['macropad', '--verbose', 'monitor']):
            verbose_args = cli.parse_args()
        with patch('sys.argv', ['macropad', '--debug', 'monitor']):
            debug_args = cli.parse_args()
        with patch('sys.argv', ['macropad', '--action-debug', 'listen']):
            action_debug_args = cli.parse_args()

        self.assertTrue(verbose_args.verbose)
        self.assertTrue(debug_args.debug)
        self.assertTrue(action_debug_args.action_debug)

    def test_action_debug_enables_debug_logging(self):
        args = SimpleNamespace(
            subcommand='validate',
            verbose=False,
            debug=False,
            action_debug=True,
        )

        with (
            patch('macropad.cli.configure_logging') as configure_logging,
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.validate.run', return_value=0),
        ):
            cli.main()

        configure_logging.assert_called_once_with(verbose=False, debug=True)


class SupervisionCycleTests(unittest.TestCase):
    def test_supervisor_ticks_without_watchdog_events(self):
        profile_supervisor = SimpleNamespace(tick=Mock())

        listen.run_supervision_cycle(
            profile_supervisor,
            SimpleNamespace(),
            queue.SimpleQueue(),
            profile_watcher.ProfileReloadScheduler(),
        )

        profile_supervisor.tick.assert_called_once_with()

    def test_supervision_cycle_serves_current_runtime_status(self):
        snapshot = {'pid': 123, 'workers': []}
        profile_supervisor = SimpleNamespace(
            tick=Mock(),
            status_snapshot=Mock(return_value=snapshot),
        )
        status_server = Mock()

        listen.run_supervision_cycle(
            profile_supervisor,
            SimpleNamespace(),
            queue.SimpleQueue(),
            profile_watcher.ProfileReloadScheduler(),
            status_server,
        )

        status_server.poll.assert_called_once_with(snapshot)

    def test_reload_runs_once_after_all_changes_are_quiet(self):
        profile_supervisor = SimpleNamespace(tick=Mock())
        args = SimpleNamespace()
        reload_requests = queue.SimpleQueue()
        reload_scheduler = profile_watcher.ProfileReloadScheduler(debounce_seconds=1.0)
        reload_requests.put('/profiles/first.yml')

        with (
            patch('macropad.cli.listen.time.monotonic', side_effect=[10.0, 10.5, 11.4, 11.5]),
            patch('macropad.cli.listen.reload_profiles') as reload_profiles,
        ):
            listen.run_supervision_cycle(
                profile_supervisor,
                args,
                reload_requests,
                reload_scheduler,
            )
            reload_requests.put('/profiles/second.yml')
            listen.run_supervision_cycle(
                profile_supervisor,
                args,
                reload_requests,
                reload_scheduler,
            )
            listen.run_supervision_cycle(
                profile_supervisor,
                args,
                reload_requests,
                reload_scheduler,
            )
            listen.run_supervision_cycle(
                profile_supervisor,
                args,
                reload_requests,
                reload_scheduler,
            )

        reload_profiles.assert_called_once_with(
            profile_supervisor,
            args,
            ['/profiles/first.yml', '/profiles/second.yml'],
        )
        self.assertEqual(4, profile_supervisor.tick.call_count)


class ShutdownSignalTests(unittest.TestCase):
    def test_sigterm_handler_requests_orderly_shutdown(self):
        shutdown_requested = threading.Event()

        with patch('macropad.cli.listen.signal.signal') as install_signal:
            listen.install_shutdown_handler(shutdown_requested)

        handler = install_signal.call_args.args[1]
        handler(signal.SIGTERM, None)

        install_signal.assert_called_once_with(signal.SIGTERM, handler)
        self.assertTrue(shutdown_requested.is_set())

    def test_validate_keeps_default_sigterm_behavior(self):
        args = SimpleNamespace(subcommand='validate')

        with (
            patch('macropad.cli.configure_logging') as configure_logging,
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.validate.run', return_value=0) as run_validate,
            patch('macropad.cli.listen.install_shutdown_handler') as install_shutdown,
        ):
            exit_status = cli.main()

        self.assertEqual(0, exit_status)
        run_validate.assert_called_once_with(args)
        configure_logging.assert_called_once_with(verbose=False, debug=False)
        install_shutdown.assert_not_called()


class MainExitStatusTests(unittest.TestCase):
    def test_missing_profiles_return_failure(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=[],
            profile_directories=['/profiles'],
            watch=False,
        )

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch('macropad.cli.listen.profile_files.get_profile_paths', return_value=[]),
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
        ):
            exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        supervisor_type.return_value.start.assert_not_called()
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_default_listen_with_no_profiles_does_not_create_configuration(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            default_config_directory = pathlib.Path(temp_directory) / 'profiles'
            args = SimpleNamespace(
                subcommand='listen',
                profile_paths=[],
                profile_directories=None,
                watch=False,
            )

            with (
                patch.object(
                    profile_files,
                    'DEFAULT_CONFIG_DIR',
                    default_config_directory,
                ),
                patch('macropad.cli.listen.notifications.initialize'),
                patch('macropad.cli.listen.install_shutdown_handler'),
                patch('macropad.cli.profile_files.logger'),
                patch('macropad.cli.listen.logger') as logger,
                patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
            ):
                exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        self.assertEqual([str(default_config_directory)], args.profile_directories)
        self.assertFalse(default_config_directory.exists())
        logger.error.assert_called_once_with(
            'no profile files found; create a .yml profile or see README.md#profile-format',
            extra={'path': str(default_config_directory)},
        )
        supervisor_type.return_value.start.assert_not_called()
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_invalid_startup_configuration_returns_failure(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=['/profiles/invalid.yml'],
            profile_directories=None,
            watch=False,
        )

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
        ):
            supervisor_type.return_value.start.side_effect = ValueError('invalid binding')
            exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_requested_watch_failure_returns_failure(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=['/profiles/macros.yml'],
            profile_directories=['.'],
            watch=True,
        )

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
            patch('macropad.profile_watcher.PollingObserver') as observer_type,
        ):
            observer_type.return_value.start.side_effect = RuntimeError('observer failed')
            observer_type.return_value.is_alive.return_value = False
            exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_watch_without_directories_returns_failure_before_starting_workers(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=['/profiles/macros.yml'],
            profile_directories=None,
            watch=True,
        )

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
        ):
            exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        supervisor_type.return_value.start.assert_not_called()
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_watch_without_valid_directories_returns_failure_before_starting_workers(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=['/profiles/macros.yml'],
            profile_directories=['/profiles/missing'],
            watch=True,
        )

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch(
                'macropad.cli.listen.profile_files.get_profile_paths',
                return_value=args.profile_paths,
            ),
            patch('macropad.cli.listen.pathlib.Path') as path_type,
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
        ):
            path_type.return_value.exists.return_value = False
            exit_status = listen.run(args)

        self.assertEqual(1, exit_status)
        supervisor_type.return_value.start.assert_not_called()
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_graceful_listen_shutdown_returns_success(self):
        args = SimpleNamespace(
            subcommand='listen',
            profile_paths=['/profiles/macros.yml'],
            profile_directories=None,
            watch=False,
            action_debug=True,
        )
        shutdown_requested = Mock()
        shutdown_requested.wait.return_value = True

        with (
            patch('macropad.cli.listen.notifications.initialize'),
            patch('macropad.cli.listen.install_shutdown_handler'),
            patch('macropad.cli.listen.threading.Event', return_value=shutdown_requested),
            patch('macropad.cli.listen.runtime_status.RuntimeStatusServer'),
            patch('macropad.cli.listen.ProfileSupervisor') as supervisor_type,
        ):
            exit_status = listen.run(args)

        self.assertEqual(0, exit_status)
        supervisor_type.assert_called_once_with(
            action_debug=True,
            verbose=False,
            debug=False,
        )
        supervisor_type.return_value.shutdown.assert_called_once_with()

    def test_unexpected_os_error_returns_failure(self):
        args = SimpleNamespace(subcommand='validate')

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch('macropad.cli.validate.run', side_effect=OSError(5, 'input/output error')),
        ):
            exit_status = cli.main()

        self.assertEqual(1, exit_status)

    def test_lost_input_device_returns_success(self):
        args = SimpleNamespace(subcommand='listen')

        with (
            patch('macropad.cli.configure_logging'),
            patch('macropad.cli.parse_args', return_value=args),
            patch(
                'macropad.cli.listen.run',
                side_effect=OSError(errno.ENODEV, 'no such device'),
            ),
        ):
            exit_status = cli.main()

        self.assertEqual(0, exit_status)

    def test_module_entry_point_propagates_main_status(self):
        with (
            patch('macropad.cli.main', return_value=7),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_module('macropad', run_name='__main__')

        self.assertEqual(7, raised.exception.code)


if __name__ == '__main__':
    unittest.main()
