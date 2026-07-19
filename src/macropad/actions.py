import logging
import os
import subprocess
from dataclasses import dataclass

DEFAULT_MAX_CONCURRENT_ACTIONS = 8
logger = logging.getLogger(__name__)


@dataclass
class RunningAction:
    command: str
    process: subprocess.Popen
    context: dict


class ActionExecutor:
    def __init__(
        self,
        max_concurrent=DEFAULT_MAX_CONCURRENT_ACTIONS,
        process_factory=None,
        device=None,
        debug_output=False,
    ):
        if max_concurrent < 1:
            raise ValueError('max_concurrent must be at least 1')
        self.max_concurrent = max_concurrent
        self._process_factory = process_factory or subprocess.Popen
        self.device = device
        self.debug_output = debug_output
        self._running_actions: list[RunningAction] = []
        logger.debug(
            'action execution configured',
            extra=self._context(
                cwd='/',
                action_path=os.environ.get('PATH'),
                display=os.environ.get('DISPLAY'),
                wayland_display=os.environ.get('WAYLAND_DISPLAY'),
                session_bus='set' if os.environ.get('DBUS_SESSION_BUS_ADDRESS') else 'unset',
                mode='inherited output' if debug_output else 'discarded output',
            ),
        )

    @property
    def active_count(self) -> int:
        return len(self._running_actions)

    def submit(
        self,
        command: str,
        *,
        key: str | None = None,
        event: str | None = None,
        layer: str | None = None,
    ) -> bool:
        self.tick()
        trigger_context = {
            name: value
            for name, value in (('key', key), ('event', event), ('layer', layer))
            if value is not None
        }
        if self.active_count >= self.max_concurrent:
            logger.warning(
                'action rejected at concurrency limit',
                extra=self._context(
                    command=command,
                    count=self.active_count,
                    limit=self.max_concurrent,
                    **trigger_context,
                ),
            )
            return False

        try:
            process = self._process_factory(
                command,
                shell=True,
                cwd='/',
                stdin=subprocess.DEVNULL,
                stdout=None if self.debug_output else subprocess.DEVNULL,
                stderr=None if self.debug_output else subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as error:
            logger.error(
                'action failed to start',
                extra=self._context(command=command, error=str(error), **trigger_context),
            )
            return False

        self._running_actions.append(RunningAction(command, process, trigger_context))
        logger.info(
            'action started',
            extra=self._context(command=command, pid=process.pid, **trigger_context),
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
                    **action.context,
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
