import argparse
import logging
import pathlib
import queue
import signal
import threading
import time

from .. import notifications, profile_watcher
from ..supervisor import ProfileSupervisor
from . import profile_files

logger = logging.getLogger(__name__)


def reload_profiles(
    profile_supervisor: ProfileSupervisor,
    args: argparse.Namespace,
    changed_paths=(),
) -> bool:
    changed_paths = tuple(changed_paths)
    logger.info('reloading profiles', extra={'changed_paths': changed_paths})
    profile_paths = profile_files.get_profile_paths(args)
    try:
        profile_supervisor.reload(profile_paths)
    except Exception as error:
        logger.error(
            'profile reload failed',
            extra={
                'profiles': tuple(profile_paths),
                'changed_paths': changed_paths,
                'error': str(error),
            },
        )
        notifications.send(
            title='Macropad Configuration Error',
            message=f'Configuration reload failed: {error}',
        )
        return False

    worker_count = len(profile_supervisor.workers)
    logger.info(
        'profiles reloaded',
        extra={'count': worker_count, 'changed_paths': changed_paths},
    )
    notifications.send(
        title='Macropad Configuration Updated',
        message=f'Successfully reloaded {worker_count} profile(s)',
    )
    return True


def run_supervision_cycle(
    profile_supervisor: ProfileSupervisor,
    args: argparse.Namespace,
    reload_requests: queue.SimpleQueue,
    reload_scheduler: profile_watcher.ProfileReloadScheduler,
) -> None:
    now = time.monotonic()
    reload_scheduler.add_changes(profile_watcher.drain_reload_requests(reload_requests), now)
    changed_paths = reload_scheduler.pop_due(now)
    if changed_paths:
        logger.info('profile changes detected', extra={'changed_paths': tuple(changed_paths)})
        reload_profiles(profile_supervisor, args, changed_paths)
    profile_supervisor.tick()


def install_shutdown_handler(shutdown_requested: threading.Event) -> None:
    def request_shutdown(signum, frame):
        shutdown_requested.set()

    signal.signal(signal.SIGTERM, request_shutdown)


def run(args: argparse.Namespace) -> int:
    observer = None
    reload_requests = queue.SimpleQueue()
    reload_scheduler = profile_watcher.ProfileReloadScheduler()
    profile_supervisor = ProfileSupervisor(
        action_debug=getattr(args, 'action_debug', False),
        verbose=getattr(args, 'verbose', False),
        debug=getattr(args, 'debug', False),
    )
    shutdown_requested = threading.Event()
    install_shutdown_handler(shutdown_requested)
    notifications.initialize()

    try:
        using_default_config = False
        if not args.profile_paths and not args.profile_directories:
            args.profile_directories = [str(profile_files.DEFAULT_CONFIG_DIR)]
            using_default_config = True

        all_profile_paths = profile_files.get_profile_paths(args)
        if not all_profile_paths:
            if using_default_config:
                logger.error(
                    'no profile files found; create a .yml profile or see README.md#profile-format',
                    extra={'path': str(profile_files.DEFAULT_CONFIG_DIR)},
                )
            else:
                logger.error(
                    'no profile files found; check the requested paths or see '
                    'README.md#profile-format'
                )
            return 1

        enable_watch = args.watch or using_default_config
        watch_directories = []
        if enable_watch:
            if not args.profile_directories:
                logger.error('watch mode requires a profile directory')
                return 1

            for directory in args.profile_directories:
                directory_path = pathlib.Path(directory)
                if directory_path.exists() and directory_path.is_dir():
                    watch_directories.append(directory_path)

            if not watch_directories:
                logger.error('no valid profile directories to watch')
                return 1

        try:
            profile_supervisor.start(all_profile_paths)
        except Exception as error:
            logger.error(
                'failed to load profiles',
                extra={'profiles': tuple(all_profile_paths), 'error': str(error)},
            )
            return 1

        if enable_watch:
            try:
                observer = profile_watcher.start_profile_observer(
                    watch_directories,
                    reload_requests,
                )
            except Exception as error:
                logger.error(
                    'failed to start profile observer',
                    extra={'error': str(error)},
                )
                return 1

        try:
            while not shutdown_requested.wait(1):
                run_supervision_cycle(
                    profile_supervisor,
                    args,
                    reload_requests,
                    reload_scheduler,
                )
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        profile_watcher.stop_profile_observer(observer)
        profile_supervisor.shutdown()
