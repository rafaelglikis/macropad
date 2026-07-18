import unittest
from types import SimpleNamespace
from unittest.mock import patch

from macropad import supervisor


class FakeProcess:
    next_pid = 1000

    def __init__(self, target, args):
        self.target = target
        self.args = args
        self.alive = False
        self.terminated = False
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


class FailingProcess(FakeProcess):
    def start(self):
        if self.args[0].device == 'Broken Keyboard':
            raise RuntimeError('start failed')
        super().start()


class ProfileSupervisorTests(unittest.TestCase):
    @staticmethod
    def _prepared_profile(device_name='Macro Keyboard', config='current', path=None):
        profile = SimpleNamespace(device=device_name, config=config)
        path = path or f'/profiles/{device_name}.yml'
        return supervisor.PreparedProfile((path,), profile)

    def _create_supervisor(self):
        return supervisor.ProfileSupervisor(
            process_factory=FakeProcess,
            device_present=lambda device_name: False,
        )

    def test_workers_are_owned_by_device_name(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])

        self.assertEqual(['Macro Keyboard'], list(profile_supervisor.workers))
        self.assertTrue(profile_supervisor.workers['Macro Keyboard'].process.is_alive())

    def test_invalid_candidate_keeps_current_worker_running(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        current_process = profile_supervisor.workers['Macro Keyboard'].process

        with patch('macropad.supervisor.prepare_profiles', side_effect=ValueError('invalid profile')):
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
        removed_process = profile_supervisor.workers['Second Keyboard'].process

        with patch('macropad.supervisor.prepare_profiles', return_value=[retained_profile]):
            profile_supervisor.reload(['/profiles/macros.yml'])

        self.assertIs(retained_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertTrue(removed_process.terminated)
        self.assertEqual([5], removed_process.join_timeouts)
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
        unchanged_process = profile_supervisor.workers['Second Keyboard'].process

        with patch(
                'macropad.supervisor.prepare_profiles',
                return_value=[changed_profile, unchanged_profile],
        ):
            profile_supervisor.reload(['/profiles/macros.yml', '/profiles/second.yml'])

        self.assertTrue(current_process.terminated)
        self.assertIsNot(current_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertIs(unchanged_process, profile_supervisor.workers['Second Keyboard'].process)
        self.assertFalse(unchanged_process.terminated)

    def test_reload_restarts_failed_worker_with_unchanged_config(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        failed_process = profile_supervisor.workers['Macro Keyboard'].process
        failed_process.alive = False

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.reload(['/profiles/macros.yml'])

        self.assertIsNot(failed_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertEqual([5], failed_process.join_timeouts)
        self.assertTrue(profile_supervisor.workers['Macro Keyboard'].process.is_alive())

    def test_reload_isolates_worker_start_failures(self):
        profile_supervisor = supervisor.ProfileSupervisor(
            process_factory=FailingProcess,
            device_present=lambda device_name: False,
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
                profile_supervisor.reload([
                    '/profiles/macros.yml',
                    '/profiles/broken.yml',
                    '/profiles/second.yml',
                ])

        self.assertIs(current_process, profile_supervisor.workers['Macro Keyboard'].process)
        self.assertFalse(current_process.terminated)
        self.assertNotIn('Broken Keyboard', profile_supervisor.workers)
        self.assertTrue(profile_supervisor.workers['Second Keyboard'].process.is_alive())

    def test_shutdown_terminates_and_joins_workers(self):
        profile_supervisor = self._create_supervisor()
        prepared_profile = self._prepared_profile()

        with patch('macropad.supervisor.prepare_profiles', return_value=[prepared_profile]):
            profile_supervisor.start(['/profiles/macros.yml'])
        process = profile_supervisor.workers['Macro Keyboard'].process

        profile_supervisor.shutdown()

        self.assertTrue(process.terminated)
        self.assertEqual([5], process.join_timeouts)
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
                patch('macropad.supervisor.profiles.create_from_data') as create_from_data,
        ):
            with self.assertRaisesRegex(ValueError, 'invalid second profile'):
                supervisor.prepare_profiles(['/profiles/first.yml', '/profiles/second.yml'])

        merge_data.assert_not_called()
        create_from_data.assert_not_called()


if __name__ == '__main__':
    unittest.main()
