import multiprocessing
import time
from dataclasses import dataclass

from . import interceptor, profiles


RESTART_INITIAL_DELAY_SECONDS = 1.0
RESTART_MAX_DELAY_SECONDS = 30.0
RESTART_STABLE_SECONDS = 30.0


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
    process: multiprocessing.Process | None = None
    failure_count: int = 0
    retry_at: float | None = None
    started_at: float | None = None

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
    def __init__(self, process_factory=None, device_present=None, clock=None):
        self._process_factory = process_factory or multiprocessing.Process
        self._device_present = device_present or interceptor.has_device
        self._clock = clock or time.monotonic
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
                    and current_worker.prepared_profile.profile.config == prepared_profile.profile.config
            ):
                current_worker.prepared_profile = prepared_profile
                continue

            if current_worker:
                self.workers.pop(device_name)
                self._stop_workers([current_worker])

            worker = Worker(prepared_profile)
            self.workers[device_name] = worker
            try:
                self._launch_worker(worker)
            except Exception as error:
                self._schedule_restart(worker, self._clock(), str(error))
                start_errors.append((device_name, error))

        if start_errors:
            details = '; '.join(
                f'{device_name}: {error}'
                for device_name, error in start_errors
            )
            raise RuntimeError(f'Failed to start profile worker(s): {details}') from start_errors[0][1]

    def tick(self) -> None:
        now = self._clock()
        for worker in list(self.workers.values()):
            process = worker.process
            if process is not None and process.is_alive():
                if (
                        worker.failure_count
                        and worker.started_at is not None
                        and now - worker.started_at >= RESTART_STABLE_SECONDS
                ):
                    worker.failure_count = 0
                    worker.started_at = None
                    print(f'Restart backoff reset for {worker.device_name}')
                continue

            if process is not None:
                process.join(timeout=5)
                worker.process = None
                worker.started_at = None
                self._schedule_restart(worker, now, f'process {process.pid} exited')
                continue

            if worker.retry_at is None:
                self._schedule_restart(worker, now, 'worker is not running')
                continue
            if now < worker.retry_at:
                continue

            try:
                self._launch_worker(worker)
            except Exception as error:
                self._schedule_restart(worker, now, str(error))

    def shutdown(self) -> None:
        workers = list(self.workers.values())
        self.workers.clear()
        self._stop_workers(workers)

    def _start_prepared_profiles(self, prepared_profiles: list[PreparedProfile]) -> None:
        started_workers = {}
        try:
            for prepared_profile in prepared_profiles:
                worker = Worker(prepared_profile)
                self._launch_worker(worker)
                started_workers[worker.device_name] = worker
        except Exception:
            self._stop_workers(started_workers.values())
            raise
        self.workers = started_workers

    def _launch_worker(self, worker: Worker) -> None:
        prepared_profile = worker.prepared_profile
        process = self._process_factory(
            target=interceptor.listen,
            args=(prepared_profile.profile,),
        )
        started = False
        try:
            process.start()
            started = True
            if self._device_present(worker.device_name):
                print(f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}")
            else:
                print(
                    f"Started profile for {worker.device_name}: {', '.join(prepared_profile.paths)}. "
                    "Waiting for device..."
                )
            worker.process = process
            worker.retry_at = None
            worker.started_at = self._clock()
        except Exception:
            is_alive = process.is_alive()
            if is_alive:
                process.terminate()
            if started or is_alive:
                process.join(timeout=5)
            raise

    @staticmethod
    def _schedule_restart(worker: Worker, now: float, reason: str) -> None:
        worker.failure_count += 1
        delay = RESTART_INITIAL_DELAY_SECONDS
        for _ in range(worker.failure_count - 1):
            delay = min(delay * 2, RESTART_MAX_DELAY_SECONDS)
            if delay == RESTART_MAX_DELAY_SECONDS:
                break
        worker.retry_at = now + delay
        worker.started_at = None
        print(
            f'Worker for {worker.device_name} failed: {reason}. '
            f'Retrying in {delay:g} seconds.'
        )

    @staticmethod
    def _stop_workers(workers) -> None:
        processes = [
            worker.process
            for worker in workers
            if worker.process is not None
        ]
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=5)
