# PYTHON_ARGCOMPLETE_OK
import argparse
import errno
import logging
import pathlib
import queue
import signal
import threading
import time

import argcomplete

from . import interceptor, notifications, profile_watcher, profiles, validation
from .logging_config import configure_logging
from .supervisor import ProfileSupervisor

logger = logging.getLogger(__name__)
DEFAULT_CONFIG_DIR = pathlib.Path.home() / '.config' / 'macropad' / 'profiles'


def ensure_default_config():
    """Ensure default config directory exists with at least one sample profile."""
    if not DEFAULT_CONFIG_DIR.exists():
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            'default configuration directory created',
            extra={'path': str(DEFAULT_CONFIG_DIR)},
        )

    yml_files = list(DEFAULT_CONFIG_DIR.glob('*.yml'))
    if not yml_files:
        sample_profile_path = DEFAULT_CONFIG_DIR / 'sample_profile.yml'
        sample_yml = """device: "Sample Device"
version: '1'
bindings:
  KEY_UP:
    up:
      - notify-send 'Macropad' 'Welcome! Edit this profile in ~/.config/macropad/profiles/'
"""
        sample_profile_path.write_text(sample_yml)
        logger.info('sample profile created', extra={'path': str(sample_profile_path)})
        logger.info(
            'edit profiles in configuration directory', extra={'path': str(DEFAULT_CONFIG_DIR)}
        )
        logger.info("run 'macropad detect --generate-profile' to create a device profile")


def get_profile_paths(args: argparse.Namespace) -> list[str]:
    all_profile_paths = list(args.profile_paths) if args.profile_paths else []

    if args.profile_directories:
        for directory in args.profile_directories:
            dir_path = pathlib.Path(directory)
            if not dir_path.exists():
                logger.warning(
                    'profile directory does not exist; skipping', extra={'path': directory}
                )
                continue
            if not dir_path.is_dir():
                logger.warning(
                    'profile path is not a directory; skipping', extra={'path': directory}
                )
                continue

            yml_files = sorted(dir_path.glob('*.yml'))
            all_profile_paths.extend(str(f) for f in yml_files)

    unique_profile_paths = []
    seen_paths = set()
    for profile_path in all_profile_paths:
        canonical_path = pathlib.Path(profile_path).expanduser().resolve(strict=False)
        if canonical_path in seen_paths:
            continue
        seen_paths.add(canonical_path)
        unique_profile_paths.append(profile_path)
    return unique_profile_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Turn every keyboard into a Macropad')
    subparsers = parser.add_subparsers(title='Subcommands', dest='subcommand', required=True)

    detect_subparser = subparsers.add_parser('detect', help='Detects input device')
    detect_subparser.add_argument(
        '--generate-profile',
        help='Generates a profile for the given device.',
        action='store_true',
        dest='generate_profile',
    )

    validate_subparser = subparsers.add_parser(
        'validate',
        help='Validate profiles without opening input devices',
        description='Load, validate, and merge profiles without opening input devices.',
        epilog='See README.md#profile-format for the complete profile format.',
    )
    validate_subparser.add_argument(
        'profile_paths', nargs='*', help='Paths to macropad profile files.'
    )
    validate_subparser.add_argument(
        '--directory',
        '-d',
        action='append',
        dest='profile_directories',
        help='Directory containing profile files (.yml). Can be specified multiple times.',
    )

    listen_subparser = subparsers.add_parser('listen', help='Intercept profile device')
    listen_subparser.add_argument(
        'profile_paths', nargs='*', help='Paths to your macropad profiles.'
    )
    listen_subparser.add_argument(
        '--directory',
        '-d',
        action='append',
        dest='profile_directories',
        help='Directory containing profile files (.yml). Can be specified multiple times.',
    )
    listen_subparser.add_argument(
        '--watch',
        action='store_true',
        help='Watch profile directories for changes and automatically reload.',
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    return args


def reload_profiles(
    profile_supervisor: ProfileSupervisor,
    args: argparse.Namespace,
    changed_paths=(),
) -> bool:
    changed_paths = tuple(changed_paths)
    logger.info('reloading profiles', extra={'changed_paths': changed_paths})
    profile_paths = get_profile_paths(args)
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


def run_listen(args: argparse.Namespace) -> int:
    observer = None
    reload_requests = queue.SimpleQueue()
    reload_scheduler = profile_watcher.ProfileReloadScheduler()
    profile_supervisor = ProfileSupervisor()
    shutdown_requested = threading.Event()
    install_shutdown_handler(shutdown_requested)
    notifications.initialize()

    try:
        using_default_config = False
        if not args.profile_paths and not args.profile_directories:
            ensure_default_config()
            args.profile_directories = [str(DEFAULT_CONFIG_DIR)]
            using_default_config = True

        all_profile_paths = get_profile_paths(args)
        if not all_profile_paths:
            logger.error('no profile files found')
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


def run_detect(args: argparse.Namespace) -> int:
    device_name = interceptor.detect()
    if not args.generate_profile:
        return 0

    profile_yml = profiles.dump_yml(profiles.create_sample(device_name))
    print('----------- Profile -----------')
    print(profile_yml)
    print('-------------------------------')

    ensure_default_config()
    filename = DEFAULT_CONFIG_DIR / 'profile.yml'
    counter = 0
    while filename.exists():
        counter += 1
        filename = DEFAULT_CONFIG_DIR / f'profile_{counter}.yml'

    filename.write_text(profile_yml)
    logger.info('sample profile generated', extra={'path': str(filename)})
    return 0


def run_validate(args: argparse.Namespace) -> int:
    if not args.profile_paths and not args.profile_directories:
        args.profile_directories = [str(DEFAULT_CONFIG_DIR)]

    profile_paths = get_profile_paths(args)
    if not profile_paths:
        logger.error('no profile files found')
        return 1
    return validation.run(profile_paths)


def main() -> int:
    configure_logging()
    try:
        args = parse_args()
        if args.subcommand == 'listen':
            return run_listen(args)
        if args.subcommand == 'detect':
            return run_detect(args)
        return run_validate(args)
    except KeyboardInterrupt:
        logger.info('keyboard interrupt received; exiting')
    except OSError as error:
        if error.errno == errno.ENODEV:
            logger.warning('input device lost; exiting', extra={'error': str(error)})
        else:
            logger.exception('operating system error; exiting', extra={'error': str(error)})
            return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
