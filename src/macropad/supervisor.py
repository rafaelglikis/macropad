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
        self.shutdown()
        self._start_prepared_profiles(prepared_profiles)

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
                process = self._process_factory(
                    target=interceptor.listen,
                    args=(prepared_profile.profile,),
                )
                process.start()
                worker = Worker(prepared_profile, process)
                started_workers[worker.device_name] = worker
                if self._device_present(worker.device_name):
                    print(f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}")
                else:
                    print(
                        f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}. "
                        "Waiting for device..."
                    )
        except Exception:
            self._stop_workers(started_workers.values())
            raise
        self.workers = started_workers

    @staticmethod
    def _stop_workers(workers) -> None:
        workers = list(workers)
        for worker in workers:
            if worker.process.is_alive():
                worker.process.terminate()
        for worker in workers:
            worker.process.join(timeout=5)
