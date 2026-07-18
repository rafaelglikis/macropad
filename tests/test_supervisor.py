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


class ProfileSupervisorTests(unittest.TestCase):
    @staticmethod
    def _prepared_profile(device_name='Macro Keyboard'):
        profile = SimpleNamespace(device=device_name)
        return supervisor.PreparedProfile(('/profiles/macros.yml',), profile)

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
