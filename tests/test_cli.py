import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from macropad import cli


class ProfileReloadHandlerTests(unittest.TestCase):
    def test_file_event_is_queued_without_running_reload_work(self):
        reload_requests = queue.SimpleQueue()
        event_handler = cli.ProfileReloadHandler(reload_requests)
        event = SimpleNamespace(is_directory=False, src_path='/profiles/macros.yml')

        with patch('macropad.cli.time.monotonic', return_value=10.0):
            event_handler.on_any_event(event)

        self.assertEqual(['/profiles/macros.yml'], cli.drain_reload_requests(reload_requests))

    def test_reload_requests_are_drained_as_one_batch(self):
        reload_requests = queue.SimpleQueue()
        reload_requests.put('/profiles/first.yml')
        reload_requests.put('/profiles/second.yml')

        self.assertEqual(
            ['/profiles/first.yml', '/profiles/second.yml'],
            cli.drain_reload_requests(reload_requests),
        )
        self.assertEqual([], cli.drain_reload_requests(reload_requests))


class ProfileReloadTests(unittest.TestCase):
    def test_success_notification_uses_supervisor_worker_count(self):
        profile_supervisor = SimpleNamespace(
            workers={'first': object(), 'second': object()},
            reload=Mock(),
        )
        args = SimpleNamespace()

        with (
                patch('macropad.cli.get_profile_paths', return_value=['/profiles/macros.yml']),
                patch('macropad.cli.utils.send_notification') as send_notification,
        ):
            succeeded = cli.reload_profiles(profile_supervisor, args)

        self.assertTrue(succeeded)
        profile_supervisor.reload.assert_called_once_with(['/profiles/macros.yml'])
        send_notification.assert_called_once_with(
            title='Macropad Configuration Updated',
            message='Successfully reloaded 2 profile(s)',
        )


class SupervisionCycleTests(unittest.TestCase):
    def test_supervisor_ticks_without_watchdog_events(self):
        profile_supervisor = SimpleNamespace(tick=Mock())

        cli.run_supervision_cycle(
            profile_supervisor,
            SimpleNamespace(),
            queue.SimpleQueue(),
        )

        profile_supervisor.tick.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
