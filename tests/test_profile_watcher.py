import queue
import unittest
from types import SimpleNamespace

from macropad import profile_watcher


class ProfileReloadHandlerTests(unittest.TestCase):
    def test_file_event_is_queued_without_running_reload_work(self):
        reload_requests = queue.SimpleQueue()
        event_handler = profile_watcher.ProfileReloadHandler(reload_requests)
        event = SimpleNamespace(is_directory=False, src_path='/profiles/macros.yml')

        event_handler.on_any_event(event)

        self.assertEqual(
            ['/profiles/macros.yml'],
            profile_watcher.drain_reload_requests(reload_requests),
        )

    def test_atomic_move_queues_destination_profile(self):
        reload_requests = queue.SimpleQueue()
        event_handler = profile_watcher.ProfileReloadHandler(reload_requests)
        event = SimpleNamespace(
            is_directory=False,
            src_path='/profiles/.macros.yml.tmp',
            dest_path='/profiles/macros.yml',
        )

        event_handler.on_any_event(event)

        self.assertEqual(
            ['/profiles/macros.yml'],
            profile_watcher.drain_reload_requests(reload_requests),
        )

    def test_profile_rename_queues_source_and_destination(self):
        reload_requests = queue.SimpleQueue()
        event_handler = profile_watcher.ProfileReloadHandler(reload_requests)
        event = SimpleNamespace(
            is_directory=False,
            src_path='/profiles/old.yml',
            dest_path='/profiles/new.yml',
        )

        event_handler.on_any_event(event)

        self.assertEqual(
            ['/profiles/old.yml', '/profiles/new.yml'],
            profile_watcher.drain_reload_requests(reload_requests),
        )

    def test_reload_requests_are_drained_as_one_batch(self):
        reload_requests = queue.SimpleQueue()
        reload_requests.put('/profiles/first.yml')
        reload_requests.put('/profiles/second.yml')

        self.assertEqual(
            ['/profiles/first.yml', '/profiles/second.yml'],
            profile_watcher.drain_reload_requests(reload_requests),
        )
        self.assertEqual([], profile_watcher.drain_reload_requests(reload_requests))


class ProfileReloadSchedulerTests(unittest.TestCase):
    def test_reload_becomes_due_after_quiet_period(self):
        scheduler = profile_watcher.ProfileReloadScheduler(debounce_seconds=1.0)

        scheduler.add_changes(['/profiles/macros.yml'], now=10.0)

        self.assertEqual([], scheduler.pop_due(now=10.99))
        self.assertEqual(['/profiles/macros.yml'], scheduler.pop_due(now=11.0))
        self.assertEqual([], scheduler.pop_due(now=12.0))

    def test_new_changes_reset_deadline_and_are_coalesced(self):
        scheduler = profile_watcher.ProfileReloadScheduler(debounce_seconds=1.0)

        scheduler.add_changes(['/profiles/first.yml'], now=10.0)
        scheduler.add_changes(
            ['/profiles/second.yml', '/profiles/first.yml'],
            now=10.5,
        )

        self.assertEqual([], scheduler.pop_due(now=11.0))
        self.assertEqual(
            ['/profiles/first.yml', '/profiles/second.yml'],
            scheduler.pop_due(now=11.5),
        )


if __name__ == '__main__':
    unittest.main()
