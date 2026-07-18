import multiprocessing
from dataclasses import dataclass

from . import interceptor, profiles


@dataclass(frozen=True)
class PreparedProfile:
    paths: tuple[str, ...]
    profile: profiles.Profile

    @property
    def device_name(self) -> str:
        return self.profile.device


@dataclass
class Worker:
    prepared_profile: PreparedProfile
    process: multiprocessing.Process

    @property
    def device_name(self) -> str:
        return self.prepared_profile.device_name


def prepare_profiles(profile_paths: list[str]) -> list[PreparedProfile]:
    profiles_by_device = {}

    for profile_path in profile_paths:
        profile_data = profiles.load_yml(profile_path)
        profiles_by_device.setdefault(profile_data.device, []).append((profile_path, profile_data))

    prepared_profiles = []
    for profile_fragments in profiles_by_device.values():
        paths = tuple(profile_path for profile_path, _ in profile_fragments)
        profile = profiles.create_from_data(
            profiles.merge_data([profile_data for _, profile_data in profile_fragments])
        )
        prepared_profiles.append(PreparedProfile(paths, profile))

    return prepared_profiles


class ProfileSupervisor:
    def __init__(self, process_factory=None, device_present=None):
        self._process_factory = process_factory or multiprocessing.Process
        self._device_present = device_present or interceptor.has_device
        self.workers: dict[str, Worker] = {}

    def start(self, profile_paths: list[str]) -> None:
        if self.workers:
            raise RuntimeError('Profile workers are already running')
        self._start_prepared_profiles(prepare_profiles(profile_paths))

    def reload(self, profile_paths: list[str]) -> None:
        prepared_profiles = prepare_profiles(profile_paths)
        prepared_by_device = {
            prepared_profile.device_name: prepared_profile
            for prepared_profile in prepared_profiles
        }

        removed_workers = [
            self.workers.pop(device_name)
            for device_name in list(self.workers)
            if device_name not in prepared_by_device
        ]
        self._stop_workers(removed_workers)

        start_errors = []
        for device_name, prepared_profile in prepared_by_device.items():
            current_worker = self.workers.get(device_name)
            if (
                    current_worker
                    and current_worker.process.is_alive()
                    and current_worker.prepared_profile.profile.config == prepared_profile.profile.config
            ):
                current_worker.prepared_profile = prepared_profile
                continue

            if current_worker:
                self.workers.pop(device_name)
                self._stop_workers([current_worker])

            try:
                self.workers[device_name] = self._start_worker(prepared_profile)
            except Exception as error:
                start_errors.append((device_name, error))

        if start_errors:
            details = '; '.join(
                f'{device_name}: {error}'
                for device_name, error in start_errors
            )
            raise RuntimeError(f'Failed to start profile worker(s): {details}') from start_errors[0][1]

    def failed_workers(self) -> list[Worker]:
        return [worker for worker in self.workers.values() if not worker.process.is_alive()]

    def join(self) -> None:
        for worker in self.workers.values():
            worker.process.join()

    def shutdown(self) -> None:
        workers = list(self.workers.values())
        self.workers.clear()
        self._stop_workers(workers)

    def _start_prepared_profiles(self, prepared_profiles: list[PreparedProfile]) -> None:
        started_workers = {}
        try:
            for prepared_profile in prepared_profiles:
                worker = self._start_worker(prepared_profile)
                started_workers[worker.device_name] = worker
        except Exception:
            self._stop_workers(started_workers.values())
            raise
        self.workers = started_workers

    def _start_worker(self, prepared_profile: PreparedProfile) -> Worker:
        process = self._process_factory(
            target=interceptor.listen,
            args=(prepared_profile.profile,),
        )
        started = False
        try:
            process.start()
            started = True
            worker = Worker(prepared_profile, process)
            if self._device_present(worker.device_name):
                print(f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}")
            else:
                print(
                    f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}. "
                    "Waiting for device..."
                )
            return worker
        except Exception:
            is_alive = process.is_alive()
            if is_alive:
                process.terminate()
            if started or is_alive:
                process.join(timeout=5)
            raise

    @staticmethod
    def _stop_workers(workers) -> None:
        workers = list(workers)
        for worker in workers:
            if worker.process.is_alive():
                worker.process.terminate()
        for worker in workers:
            worker.process.join(timeout=5)
