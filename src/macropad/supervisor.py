import logging
import multiprocessing
import os
import queue
import time
from dataclasses import dataclass
from typing import Any

from . import interceptor, profiles
from . import worker as worker_runtime
from .profiles import PreparedProfile

RESTART_INITIAL_DELAY_SECONDS = 1.0
RESTART_MAX_DELAY_SECONDS = 30.0
RESTART_STABLE_SECONDS = 30.0
SHUTDOWN_TIMEOUT_SECONDS = 5.0
KILL_JOIN_TIMEOUT_SECONDS = 1.0
logger = logging.getLogger(__name__)


@dataclass
class Worker:
    prepared_profile: PreparedProfile
    shutdown_event: Any
    process: multiprocessing.Process | None = None
    failure_count: int = 0
    retry_at: float | None = None
    started_at: float | None = None
    runtime_id: int = 0
    state: str = 'starting'
    matched_paths: tuple[str, ...] = ()
    error: str | None = None

    @property
    def device_name(self) -> str:
        return self.prepared_profile.device_name


def prepare_profiles(profile_paths: list[str]) -> list[PreparedProfile]:
    return profiles.prepare_profiles(profile_paths)


class ProfileSupervisor:
    def __init__(
        self,
        process_factory=None,
        device_present=None,
        clock=None,
        shutdown_event_factory=None,
        action_debug=False,
        verbose=False,
        debug=False,
        status_queue=None,
        status_publisher=None,
    ):
        self._process_factory = process_factory or multiprocessing.Process
        self._device_present = device_present or interceptor.has_device
        self._clock = clock or time.monotonic
        self._shutdown_event_factory = shutdown_event_factory or multiprocessing.Event
        self.action_debug = action_debug
        self.verbose = verbose
        self.debug = debug
        self._owns_status_queue = status_queue is None
        self._status_queue = status_queue if status_queue is not None else multiprocessing.Queue()
        self._next_runtime_id = 1
        self.configuration_error = None
        self.status_publisher = status_publisher
        self.workers: dict[str, Worker] = {}

    def start(self, profile_paths: list[str]) -> None:
        if self.workers:
            raise RuntimeError('Profile workers are already running')
        self._start_prepared_profiles(prepare_profiles(profile_paths))

    def reload(self, profile_paths: list[str]) -> None:
        prepared_profiles = prepare_profiles(profile_paths)
        prepared_by_device = {
            prepared_profile.device_name: prepared_profile for prepared_profile in prepared_profiles
        }

        removed_workers = [
            worker
            for device_name, worker in self.workers.items()
            if device_name not in prepared_by_device
        ]
        self._stop_workers(removed_workers)
        for worker in removed_workers:
            self.workers.pop(worker.device_name)

        start_errors = []
        for device_name, prepared_profile in prepared_by_device.items():
            current_worker = self.workers.get(device_name)
            if current_worker and current_worker.prepared_profile.config == prepared_profile.config:
                current_worker.prepared_profile = prepared_profile
                continue

            if current_worker:
                self._stop_workers([current_worker])
                self.workers.pop(device_name)

            worker = self._new_worker(prepared_profile)
            self.workers[device_name] = worker
            try:
                self._launch_worker(worker)
            except Exception as error:
                self._schedule_restart(worker, self._clock(), str(error))
                start_errors.append((device_name, error))

        if start_errors:
            details = '; '.join(f'{device_name}: {error}' for device_name, error in start_errors)
            raise RuntimeError(f'Failed to start profile worker(s): {details}') from start_errors[
                0
            ][1]

    def tick(self) -> None:
        self._drain_status_updates()
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
                    logger.info(
                        'worker restart backoff reset',
                        extra={'device': worker.device_name, 'pid': process.pid},
                    )
                continue

            if process is not None:
                process.join(timeout=5)
                self._drain_status_updates()
                reason = worker.error or f'process {process.pid} exited'
                error_paths = worker.matched_paths if worker.error else ()
                worker.process = None
                worker.started_at = None
                self._schedule_restart(worker, now, reason, error_paths)
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
        self._drain_status_updates()

    def shutdown(self) -> None:
        workers = list(self.workers.values())
        self._stop_workers(workers)
        self._drain_status_updates()
        self.workers.clear()
        if self._owns_status_queue:
            self._status_queue.close()
            self._status_queue.join_thread()

    def _start_prepared_profiles(self, prepared_profiles: list[PreparedProfile]) -> None:
        started_workers = {}
        try:
            for prepared_profile in prepared_profiles:
                worker = self._new_worker(prepared_profile)
                self._launch_worker(worker)
                started_workers[worker.device_name] = worker
        except Exception:
            self._stop_workers(started_workers.values())
            raise
        self.workers = started_workers
        self._publish_status()

    def _launch_worker(self, worker: Worker) -> None:
        prepared_profile = worker.prepared_profile
        worker.shutdown_event.clear()
        worker.runtime_id = self._next_runtime_id
        self._next_runtime_id += 1
        worker.state = 'starting'
        worker.matched_paths = ()
        worker.error = None
        process = self._process_factory(
            target=worker_runtime.run,
            args=(
                prepared_profile.config,
                worker.shutdown_event,
                self.action_debug,
                self.verbose,
                self.debug,
                self._status_queue,
                worker.runtime_id,
            ),
        )
        started = False
        try:
            process.start()
            started = True
            worker.process = process
            device_present = self._device_present(worker.device_name)
            logger.info(
                'worker started',
                extra={
                    'device': worker.device_name,
                    'profiles': prepared_profile.paths,
                    'pid': process.pid,
                    'mode': 'listening' if device_present else 'waiting',
                },
            )
            worker.retry_at = None
            worker.started_at = self._clock()
        except Exception:
            is_alive = process.is_alive()
            if started or is_alive:
                worker.process = process
                self._stop_workers([worker])
                worker.process = None
            raise

    @staticmethod
    def _schedule_restart(worker: Worker, now: float, reason: str, paths=()) -> None:
        worker.failure_count += 1
        delay = RESTART_INITIAL_DELAY_SECONDS
        for _ in range(worker.failure_count - 1):
            delay = min(delay * 2, RESTART_MAX_DELAY_SECONDS)
            if delay == RESTART_MAX_DELAY_SECONDS:
                break
        worker.retry_at = now + delay
        worker.started_at = None
        worker.state = 'backing_off'
        worker.matched_paths = tuple(paths)
        worker.error = reason
        logger.warning(
            'worker failed; restart scheduled',
            extra={
                'device': worker.device_name,
                'retry_seconds': delay,
                'error': reason,
            },
        )

    def _stop_workers(self, workers) -> None:
        workers = list(workers)
        for worker in workers:
            worker.state = 'shutting_down'
            worker.shutdown_event.set()
        self._publish_status()

        processes = [worker.process for worker in workers if worker.process is not None]
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))

        unresponsive_processes = [process for process in processes if process.is_alive()]
        for process in unresponsive_processes:
            logger.warning(
                'worker did not stop gracefully; killing it',
                extra={'pid': process.pid},
            )
            process.kill()
        for process in unresponsive_processes:
            process.join(timeout=KILL_JOIN_TIMEOUT_SECONDS)

        surviving_processes = [process for process in unresponsive_processes if process.is_alive()]
        if surviving_processes:
            pids = ', '.join(str(process.pid) for process in surviving_processes)
            raise RuntimeError(f'Worker process(es) did not stop: {pids}')

    def _new_worker(self, prepared_profile: PreparedProfile) -> Worker:
        return Worker(prepared_profile, self._shutdown_event_factory())

    def _drain_status_updates(self) -> None:
        workers_by_id = {worker.runtime_id: worker for worker in self.workers.values()}
        while True:
            try:
                update = self._status_queue.get_nowait()
            except queue.Empty:
                return
            worker = workers_by_id.get(update.get('worker_id'))
            if (
                worker is None
                or worker.process is None
                or worker.device_name != update.get('device')
            ):
                continue
            worker.state = update['state']
            worker.matched_paths = tuple(update.get('paths', ()))
            worker.error = update.get('error')

    def status_snapshot(self, drain_updates: bool = True) -> dict:
        if drain_updates:
            self._drain_status_updates()
        now = self._clock()
        workers = []
        for worker in sorted(self.workers.values(), key=lambda item: item.device_name):
            retry_seconds = None
            if worker.retry_at is not None:
                retry_seconds = max(0.0, worker.retry_at - now)
            workers.append(
                {
                    'device': worker.device_name,
                    'profiles': list(worker.prepared_profile.paths),
                    'state': worker.state,
                    'pid': worker.process.pid if worker.process is not None else None,
                    'paths': list(worker.matched_paths),
                    'error': worker.error,
                    'retry_seconds': retry_seconds,
                }
            )
        return {
            'pid': os.getpid(),
            'configuration_error': self.configuration_error,
            'workers': workers,
        }

    def _publish_status(self) -> None:
        if self.status_publisher is not None:
            self.status_publisher(self.status_snapshot(drain_updates=False))
