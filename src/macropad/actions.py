import subprocess
from dataclasses import dataclass


DEFAULT_MAX_CONCURRENT_ACTIONS = 8


@dataclass
class RunningAction:
    command: str
    process: subprocess.Popen


class ActionExecutor:
    def __init__(self, max_concurrent=DEFAULT_MAX_CONCURRENT_ACTIONS, process_factory=None):
        if max_concurrent < 1:
            raise ValueError('max_concurrent must be at least 1')
        self.max_concurrent = max_concurrent
        self._process_factory = process_factory or subprocess.Popen
        self._running_actions: list[RunningAction] = []

    @property
    def active_count(self) -> int:
        return len(self._running_actions)

    def submit(self, command: str) -> bool:
        self.tick()
        if self.active_count >= self.max_concurrent:
            print(
                f'Action limit reached ({self.max_concurrent}); '
                f'skipping command: {command}'
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
            print(f'Failed to execute command: {error}')
            return False

        self._running_actions.append(RunningAction(command, process))
        return True

    def tick(self) -> None:
        running_actions = []
        for action in self._running_actions:
            exit_status = action.process.poll()
            if exit_status is None:
                running_actions.append(action)
                continue
            print(f'Command exited with status {exit_status}: {action.command}')
        self._running_actions = running_actions

    def shutdown(self) -> None:
        self.tick()
        if self._running_actions:
            print(
                f'Detaching {len(self._running_actions)} running action(s) '
                'during worker shutdown'
            )
        self._running_actions.clear()
