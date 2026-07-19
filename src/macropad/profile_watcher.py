import logging
import pathlib
import queue

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

PROFILE_RELOAD_DEBOUNCE_SECONDS = 1.0
logger = logging.getLogger(__name__)


class ProfileReloadHandler(FileSystemEventHandler):
    def __init__(self, reload_requests: queue.SimpleQueue):
        self.reload_requests = reload_requests

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory:
            return

        event_paths = (event.src_path, getattr(event, 'dest_path', None))
        for event_path in dict.fromkeys(event_paths):
            if event_path and event_path.endswith('.yml'):
                self.reload_requests.put(event_path)


def drain_reload_requests(reload_requests: queue.SimpleQueue) -> list[str]:
    changed_paths = []
    while True:
        try:
            changed_paths.append(reload_requests.get_nowait())
        except queue.Empty:
            return changed_paths


class ProfileReloadScheduler:
    def __init__(self, debounce_seconds: float = PROFILE_RELOAD_DEBOUNCE_SECONDS):
        self.debounce_seconds = debounce_seconds
        self._changed_paths = {}
        self._reload_at = None

    def add_changes(self, changed_paths: list[str], now: float) -> None:
        if not changed_paths:
            return
        for changed_path in changed_paths:
            self._changed_paths.setdefault(changed_path, None)
        self._reload_at = now + self.debounce_seconds

    def pop_due(self, now: float) -> list[str]:
        if self._reload_at is None or now < self._reload_at:
            return []

        changed_paths = list(self._changed_paths)
        self._changed_paths.clear()
        self._reload_at = None
        return changed_paths


def start_profile_observer(
    watch_directories: list[pathlib.Path],
    reload_requests: queue.SimpleQueue,
) -> PollingObserver:
    observer = PollingObserver()
    event_handler = ProfileReloadHandler(reload_requests)
    for directory in watch_directories:
        observer.schedule(
            event_handler,
            str(directory),
            recursive=False,
        )
        logger.info('watching profile directory', extra={'path': str(directory)})

    try:
        observer.start()
    except Exception:
        if observer.is_alive():
            observer.stop()
            observer.join()
        raise

    logger.info('profile watch mode enabled')
    return observer


def stop_profile_observer(observer: PollingObserver | None) -> None:
    if observer is not None and observer.is_alive():
        observer.stop()
        observer.join()
