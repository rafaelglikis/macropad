import logging
import subprocess
from dataclasses import dataclass

DEFAULT_MAX_CONCURRENT_ACTIONS = 8
logger = logging.getLogger(__name__)


@dataclass
class RunningAction:
    command: str
    process: subprocess.Popen


class ActionExecutor:
    def __init__(
        self,
        max_concurrent=DEFAULT_MAX_CONCURRENT_ACTIONS,
        process_factory=None,
        device=None,
    ):
        if max_concurrent < 1:
            raise ValueError('max_concurrent must be at least 1')
        self.max_concurrent = max_concurrent
        self._process_factory = process_factory or subprocess.Popen
        self.device = device
        self._running_actions: list[RunningAction] = []

    @property
    def active_count(self) -> int:
        return len(self._running_actions)

    def submit(self, command: str) -> bool:
        self.tick()
        if self.active_count >= self.max_concurrent:
            logger.warning(
                'action rejected at concurrency limit',
                extra=self._context(command=command, limit=self.max_concurrent),
            )
            return False

        try:
            process = self._process_factory(
                command,
                shell=True,
                cwd='/',
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as error:
            logger.error(
                'action failed to start',
                extra=self._context(command=command, error=str(error)),
            )
            return False

        self._running_actions.append(RunningAction(command, process))
        logger.info(
            'action started',
            extra=self._context(command=command, pid=process.pid),
        )
        return True

    def tick(self) -> None:
        running_actions = []
        for action in self._running_actions:
            exit_status = action.process.poll()
            if exit_status is None:
                running_actions.append(action)
                continue
            log_method = logger.info if exit_status == 0 else logger.warning
            log_method(
                'action exited',
                extra=self._context(
                    command=action.command,
                    pid=action.process.pid,
                    exit_status=exit_status,
                ),
            )
        self._running_actions = running_actions

    def shutdown(self) -> None:
        self.tick()
        if self._running_actions:
            logger.info(
                'detaching running actions during worker shutdown',
                extra=self._context(count=len(self._running_actions)),
            )
        self._running_actions.clear()

    def _context(self, **values) -> dict:
        if self.device is not None:
            values['device'] = self.device
        return values
