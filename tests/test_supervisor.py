import multiprocessing
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from macropad import supervisor


class FakeProcess:
    next_pid = 1000

    def __init__(self, target, args):
        self.target = target
        self.args = args
        self.alive = False
        self.terminated = False
        self.killed = False
        self.join_timeouts = []
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False
        self.terminated = True

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)
        if self.args[1].is_set() and not getattr(self, 'ignore_shutdown', False):
            self.alive = False

    def kill(self):
        self.alive = False
        self.killed = True


class UnresponsiveProcess(FakeProcess):
    ignore_shutdown = True


class UnkillableProcess(UnresponsiveProcess):
    def kill(self):
        self.killed = True


class FailingProcess(FakeProcess):
    def start(self):
        if self.args[0].device == 'Broken Keyboard':
            raise RuntimeError('start failed')
        super().start()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeEvent:
    def __init__(self):
        self.value = False

    def clear(self):
        self.value = False

    def is_set(self):
        return self.value

    def set(self):
        self.value = True


def exit_immediately():
    pass


def wait_until_stopped(stop_event):
    stop_event.wait()


class RealProcessFactory:
    def __init__(self):
        self.processes = []

    def __call__(self, target, args):
        if self.processes:
            process = multiprocessing.Process(
                target=wait_until_stopped,
                args=(args[1],),
            )
        else:
            process = multiprocessing.Process(target=exit_immediately)
        self.processes.append(process)
        return process


class ProfileSupervisorTests(unittest.TestCase):
    @staticmethod
    def _prepared_profile(device_name='Macro Keyboard', config='current', path=None):
        profile_config = SimpleNamespace(device=device_name, revision=config)
        path = path or f'/profiles/{device_name}.yml'
        return supervisor.PreparedProfile((path,), profile_config)

    def _create_supervisor(self, clock=None, process_factory=FakeProcess):
        return supervisor.ProfileSupervisor(
            process_factory=process_factory,
            device_present=lambda device_name: False,
            clock=clock,
            shutdown_event_factory=FakeEvent,
            status_queue=queue.Queue(),
        )

    def test_workers_are_owned_by_device_name(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])

        self.assertEqual(['Macro Keyboard'], list(profile_supervisor.workers))
        process = profile_supervisor.workers['Macro Keyboard'].process
        self.assertTrue(process.is_alive())
        self.assertIs(supervisor.worker_runtime.run, process.target)
        self.assertIs(prepared_profile.config, process.args[0])
        self.assertFalse(process.args[2])
        self.assertFalse(process.args[3])
        self.assertFalse(process.args[4])

    def test_action_debug_is_forwarded_to_worker_process(self):
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            shutdown_event_factory=FakeEvent,
            action_debug=True,
            status_queue=queue.Queue(),
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])

        process = profile_supervisor.workers['Macro Keyboard'].process
        self.assertTrue(process.args[2])

    def test_logging_options_are_forwarded_to_worker_process(self):
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            shutdown_event_factory=FakeEvent,
            verbose=True,
            debug=True,
            status_queue=queue.Queue(),
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])

        process = profile_supervisor.workers['Macro Keyboard'].process
        self.assertTrue(process.args[3])
        self.assertTrue(process.args[4])

    def test_worker_updates_are_exposed_in_status_snapshot(self):
        status_queue = queue.Queue()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            shutdown_event_factory=FakeEvent,
            status_queue=status_queue,
        )
        prepared_profile = self._prepared_profile(path='/profiles/macro.yml')

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macro.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        status_queue.put(
            {
                'worker_id': worker.runtime_id,
                'device': worker.device_name,
                'state': 'listening',
                'paths': ('/dev/input/event12',),
                'error': None,
            }
        )

        snapshot = profile_supervisor.status_snapshot()

        self.assertEqual('listening', snapshot['workers'][0]['state'])
        self.assertEqual(['/dev/input/event12'], snapshot['workers'][0]['paths'])
        self.assertEqual(['/profiles/macro.yml'], snapshot['workers'][0]['profiles'])

    def test_stale_worker_update_does_not_replace_current_state(self):
        status_queue = queue.Queue()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            shutdown_event_factory=FakeEvent,
            status_queue=status_queue,
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        status_queue.put(
            {
                'worker_id': worker.runtime_id - 1,
                'device': worker.device_name,
                'state': 'error',
                'paths': (),
                'error': 'stale failure',
            }
        )

        snapshot = profile_supervisor.status_snapshot()

        self.assertEqual('starting', snapshot['workers'][0]['state'])
        self.assertIsNone(snapshot['workers'][0]['error'])

    def test_restart_uses_new_generation_and_ignores_old_process_update(self):
        clock = FakeClock()
        status_queue = queue.Queue()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            clock=clock,
            shutdown_event_factory=FakeEvent,
            status_queue=status_queue,
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        old_runtime_id = worker.runtime_id
        worker.process.alive = False
        profile_supervisor.tick()
        clock.advance(1)
        profile_supervisor.tick()
        self.assertNotEqual(old_runtime_id, worker.runtime_id)

        status_queue.put(
            {
                'worker_id': old_runtime_id,
                'device': worker.device_name,
                'state': 'error',
                'paths': ('/dev/input/event1',),
                'error': 'old process failure',
            }
        )

        snapshot = profile_supervisor.status_snapshot()

        self.assertEqual('starting', snapshot['workers'][0]['state'])
        self.assertIsNone(snapshot['workers'][0]['error'])

    def test_worker_error_and_path_are_preserved_during_backoff(self):
        clock = FakeClock()
        status_queue = queue.Queue()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            clock=clock,
            shutdown_event_factory=FakeEvent,
            status_queue=status_queue,
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        status_queue.put(
            {
                'worker_id': worker.runtime_id,
                'device': worker.device_name,
                'state': 'error',
                'paths': ('/dev/input/event12',),
                'error': '[Errno 16] device busy',
            }
        )
        worker.process.alive = False

        profile_supervisor.tick()
        snapshot = profile_supervisor.status_snapshot()

        self.assertEqual('backing_off', snapshot['workers'][0]['state'])
        self.assertEqual('[Errno 16] device busy', snapshot['workers'][0]['error'])
        self.assertEqual(['/dev/input/event12'], snapshot['workers'][0]['paths'])

    def test_shutdown_state_is_published_before_waiting_for_workers(self):
        status_publisher = Mock()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
            shutdown_event_factory=FakeEvent,
            status_queue=queue.Queue(),
            status_publisher=status_publisher,
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        status_publisher.reset_mock()

        profile_supervisor.shutdown()

        published_states = [
            worker['state']
            for published in status_publisher.call_args_list
            for worker in published.args[0]['workers']
        ]
        self.assertIn('shutting_down', published_states)

    def test_invalid_candidate_keeps_current_worker_running(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process

        with patch(
            'macropad.supervisor.prepare_profiles', side_effect=ValueError('invalid profile')
        ):
            with self.assertRaisesRegex(ValueError, 'invalid profile'):
                profile_supervisor.reload(['/profiles/broken.yml'])

        self.assertTrue(current_process.is_alive())
        self.assertFalse(current_process.terminated)
        self.assertIs(current_process, profile_supervisor.workers['Macro Keyboard'].process)

    def test_reload_keeps_unchanged_worker_running(self):
        profile_supervisor = self._create_supervisor()
        current_profile = self._prepared_profile(path='/profiles/old.yml')
        candidate_profile = self._prepared_profile(path='/profiles/renamed.yml')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/old.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process

        with patch('macropad.supervisor.prepare_profiles', return_value=[candidate_profile]):
            profile_supervisor.reload(['/profiles/renamed.yml'])

        current_worker = profile_supervisor.workers['Macro Keyboard']
        self.assertIs(current_process, current_worker.process)
        self.assertFalse(current_process.terminated)
        self.assertIs(candidate_profile, current_worker.prepared_profile)

    def test_reload_starts_worker_for_added_device(self):
        profile_supervisor = self._create_supervisor()
        current_profile = self._prepared_profile()
        added_profile = self._prepared_profile('Second Keyboard')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[current_profile, added_profile],
        ):
            profile_supervisor.reload(['/profiles/macros.yml', '/profiles/second.yml'])

        self.assertIs(current_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertTrue(profile_supervisor.workers['Second Keyboard'].process.is_alive())

    def test_reload_stops_worker_for_removed_device(self):
        profile_supervisor = self._create_supervisor()
        retained_profile = self._prepared_profile()
        removed_profile = self._prepared_profile('Second Keyboard')

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[retained_profile, removed_profile],
        ):
            profile_supervisor.start(['/profiles/macros.yml', '/profiles/second.yml'])
        retained_process = profile_supervisor.workers['Macro Keyboard'].process
        removed_event = profile_supervisor.workers['Second Keyboard'].shutdown_event
        removed_process = profile_supervisor.workers['Second Keyboard'].process

        with patch('macropad.supervisor.prepare_profiles', return_value=[retained_profile]):
            profile_supervisor.reload(['/profiles/macros.yml'])

        self.assertIs(retained_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertTrue(removed_event.is_set())
        self.assertFalse(removed_process.terminated)
        self.assertFalse(removed_process.killed)
        self.assertEqual(1, len(removed_process.join_timeouts))
        self.assertNotIn('Second Keyboard', profile_supervisor.workers)

    def test_reload_restarts_only_changed_worker(self):
        profile_supervisor = self._create_supervisor()
        current_profile = self._prepared_profile(config='old')
        unchanged_profile = self._prepared_profile('Second Keyboard')
        changed_profile = self._prepared_profile(config='new')

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[current_profile, unchanged_profile],
        ):
            profile_supervisor.start(['/profiles/macros.yml', '/profiles/second.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process
        current_event = profile_supervisor.workers['Macro Keyboard'].shutdown_event
        unchanged_process = profile_supervisor.workers['Second Keyboard'].process

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[changed_profile, unchanged_profile],
        ):
            profile_supervisor.reload(['/profiles/macros.yml', '/profiles/second.yml'])

        self.assertTrue(current_event.is_set())
        self.assertFalse(current_process.terminated)
        self.assertFalse(current_process.killed)
        self.assertIsNot(current_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertIs(unchanged_process, profile_supervisor.workers['Second Keyboard'].process)
        self.assertFalse(unchanged_process.terminated)

    def test_reload_does_not_replace_worker_that_survives_forced_shutdown(self):
        profile_supervisor = self._create_supervisor(process_factory=UnkillableProcess)
        current_profile = self._prepared_profile(config='old')
        changed_profile = self._prepared_profile(config='new')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_worker = profile_supervisor.workers['Macro Keyboard']

        with patch('macropad.supervisor.prepare_profiles', return_value=[changed_profile]):
            with self.assertRaisesRegex(RuntimeError, 'Worker process.*did not stop'):
                profile_supervisor.reload(['/profiles/macros.yml'])

        self.assertIs(current_worker, profile_supervisor.workers['Macro Keyboard'])
        self.assertTrue(current_worker.process.is_alive())
        self.assertTrue(current_worker.process.killed)
        self.assertEqual('old', current_worker.prepared_profile.config.revision)

    def test_reload_preserves_backoff_for_unchanged_failed_worker(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        current_profile = self._prepared_profile(path='/profiles/old.yml')
        candidate_profile = self._prepared_profile(path='/profiles/renamed.yml')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        failed_process = profile_supervisor.workers['Macro Keyboard'].process
        failed_process.alive = False
        profile_supervisor.tick()
        current_worker = profile_supervisor.workers['Macro Keyboard']

        with patch('macropad.supervisor.prepare_profiles', return_value=[candidate_profile]):
            profile_supervisor.reload(['/profiles/renamed.yml'])

        self.assertIs(current_worker, profile_supervisor.workers['Macro Keyboard'])
        self.assertIs(candidate_profile, current_worker.prepared_profile)
        self.assertIsNone(current_worker.process)
        self.assertEqual(1, current_worker.failure_count)
        self.assertEqual(1.0, current_worker.retry_at)
        self.assertEqual([5], failed_process.join_timeouts)

    def test_reload_isolates_worker_start_failures(self):
        clock = FakeClock()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FailingProcess,
            device_present=lambda device_name: False,
            clock=clock,
            shutdown_event_factory=FakeEvent,
            status_queue=queue.Queue(),
        )
        current_profile = self._prepared_profile()
        broken_profile = self._prepared_profile('Broken Keyboard')
        added_profile = self._prepared_profile('Second Keyboard')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[current_profile, broken_profile, added_profile],
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                'Failed to start profile worker.*Broken Keyboard: start failed',
            ):
                profile_supervisor.reload(
                    [
                        '/profiles/macros.yml',
                        '/profiles/broken.yml',
                        '/profiles/second.yml',
                    ]
                )

        self.assertIs(current_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertFalse(current_process.terminated)
        self.assertTrue(profile_supervisor.workers['Second Keyboard'].process.is_alive())
        broken_worker = profile_supervisor.workers['Broken Keyboard']
        self.assertIsNone(broken_worker.process)
        self.assertEqual(1, broken_worker.failure_count)
        self.assertEqual(1.0, broken_worker.retry_at)

        clock.advance(1)
        profile_supervisor.tick()

        self.assertIsNone(broken_worker.process)
        self.assertEqual(2, broken_worker.failure_count)
        self.assertEqual(3.0, broken_worker.retry_at)
        self.assertIs(current_process, profile_supervisor.workers['Macro Keyboard'].process)

    def test_failed_worker_restarts_with_capped_exponential_backoff(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']

        for failure_count, delay in enumerate((1, 2, 4, 8, 16, 30, 30), start=1):
            failed_process = worker.process
            failed_process.alive = False
            profile_supervisor.tick()

            self.assertIsNone(worker.process)
            self.assertEqual(failure_count, worker.failure_count)
            self.assertEqual(clock.now + delay, worker.retry_at)
            self.assertEqual([5], failed_process.join_timeouts)

            clock.advance(delay / 2)
            profile_supervisor.tick()
            self.assertIsNone(worker.process)

            clock.advance(delay / 2)
            profile_supervisor.tick()
            self.assertTrue(worker.process.is_alive())

    def test_real_process_exit_is_detected_and_restarted(self):
        clock = FakeClock()
        process_factory = RealProcessFactory()
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=process_factory,
            device_present=lambda device_name: False,
            clock=clock,
            status_queue=queue.Queue(),
        )
        prepared_profile = self._prepared_profile()

        try:
            with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
                profile_supervisor.start(['/profiles/macros.yml'])
            worker = profile_supervisor.workers['Macro Keyboard']
            exited_process = worker.process
            exited_process.join(timeout=2)
            self.assertFalse(exited_process.is_alive())

            profile_supervisor.tick()
            self.assertIsNone(worker.process)
            self.assertEqual(1.0, worker.retry_at)

            clock.advance(1)
            profile_supervisor.tick()

            self.assertEqual(2, len(process_factory.processes))
            self.assertTrue(worker.process.is_alive())
        finally:
            profile_supervisor.shutdown()

    def test_real_worker_stops_cleanly_from_shutdown_event(self):
        def process_factory(target, args):
            return multiprocessing.Process(
                target=wait_until_stopped,
                args=(args[1],),
            )

        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=process_factory,
            device_present=lambda device_name: False,
            status_queue=queue.Queue(),
        )
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        process = profile_supervisor.workers['Macro Keyboard'].process

        profile_supervisor.shutdown()

        self.assertFalse(process.is_alive())
        self.assertEqual(0, process.exitcode)

    def test_stable_worker_resets_restart_backoff(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        worker.process.alive = False
        profile_supervisor.tick()
        clock.advance(1)
        profile_supervisor.tick()

        clock.advance(supervisor.RESTART_STABLE_SECONDS - 1)
        profile_supervisor.tick()
        self.assertEqual(1, worker.failure_count)

        clock.advance(1)
        profile_supervisor.tick()
        self.assertEqual(0, worker.failure_count)

        worker.process.alive = False
        profile_supervisor.tick()
        self.assertEqual(1, worker.failure_count)
        self.assertEqual(clock.now + 1, worker.retry_at)

    def test_failed_worker_does_not_restart_healthy_worker(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        failed_profile = self._prepared_profile()
        healthy_profile = self._prepared_profile('Second Keyboard')

        with patch(
            'macropad.supervisor.prepare_profiles',
            return_value=[failed_profile, healthy_profile],
        ):
            profile_supervisor.start(['/profiles/macros.yml', '/profiles/second.yml'])
        failed_worker = profile_supervisor.workers['Macro Keyboard']
        healthy_process = profile_supervisor.workers['Second Keyboard'].process
        failed_worker.process.alive = False

        profile_supervisor.tick()
        clock.advance(1)
        profile_supervisor.tick()

        self.assertTrue(failed_worker.process.is_alive())
        self.assertIs(healthy_process, profile_supervisor.workers['Second Keyboard'].process)
        self.assertFalse(healthy_process.terminated)

    def test_changed_profile_bypasses_pending_backoff(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        current_profile = self._prepared_profile(config='old')
        changed_profile = self._prepared_profile(config='new')

        with patch('macropad.supervisor.prepare_profiles', return_value=[current_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_worker = profile_supervisor.workers['Macro Keyboard']
        current_worker.process.alive = False
        profile_supervisor.tick()

        with patch('macropad.supervisor.prepare_profiles', return_value=[changed_profile]):
            profile_supervisor.reload(['/profiles/macros.yml'])

        changed_worker = profile_supervisor.workers['Macro Keyboard']
        self.assertIsNot(current_worker, changed_worker)
        self.assertTrue(changed_worker.process.is_alive())
        self.assertEqual(0, changed_worker.failure_count)
        self.assertIsNone(changed_worker.retry_at)

    def test_removed_profile_cancels_pending_restart(self):
        clock = FakeClock()
        profile_supervisor = self._create_supervisor(clock)
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        worker = profile_supervisor.workers['Macro Keyboard']
        worker.process.alive = False
        profile_supervisor.tick()

        with patch('macropad.supervisor.prepare_profiles', return_value=[]):
            profile_supervisor.reload([])
        clock.advance(1)
        profile_supervisor.tick()

        self.assertEqual({}, profile_supervisor.workers)

    def test_shutdown_signals_and_joins_workers(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        shutdown_event = profile_supervisor.workers['Macro Keyboard'].shutdown_event
        process = profile_supervisor.workers['Macro Keyboard'].process

        profile_supervisor.shutdown()

        self.assertTrue(shutdown_event.is_set())
        self.assertFalse(process.terminated)
        self.assertFalse(process.killed)
        self.assertEqual(1, len(process.join_timeouts))
        self.assertEqual({}, profile_supervisor.workers)

    def test_shutdown_kills_worker_that_ignores_shutdown_event(self):
        profile_supervisor = self._create_supervisor(process_factory=UnresponsiveProcess)
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        shutdown_event = profile_supervisor.workers['Macro Keyboard'].shutdown_event
        process = profile_supervisor.workers['Macro Keyboard'].process

        profile_supervisor.shutdown()

        self.assertTrue(shutdown_event.is_set())
        self.assertTrue(process.killed)
        self.assertEqual(2, len(process.join_timeouts))
        self.assertEqual({}, profile_supervisor.workers)


class ProfilePreparationTests(unittest.TestCase):
    def test_all_files_are_loaded_before_any_profile_is_merged(self):
        first_config = SimpleNamespace(device='Macro Keyboard')

        with (
            patch(
                'macropad.supervisor.profiles.load_yml',
                side_effect=[first_config, ValueError('invalid second profile')],
            ),
            patch('macropad.supervisor.profiles.merge_data') as merge_data,
        ):
            with self.assertRaisesRegex(ValueError, 'invalid second profile'):
                supervisor.prepare_profiles(['/profiles/first.yml', '/profiles/second.yml'])

        merge_data.assert_not_called()


if __name__ == '__main__':
    unittest.main()
