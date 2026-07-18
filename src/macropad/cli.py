# PYTHON_ARGCOMPLETE_OK
import argparse
import pathlib
import queue
import signal
import time
from typing import List

import argcomplete
import notify2
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from . import interceptor, profiles, utils
from .supervisor import ProfileSupervisor
from .utils import DEFAULT_CONFIG_DIR


class ProfileReloadHandler(FileSystemEventHandler):
    def __init__(self, reload_requests: queue.SimpleQueue):
        self.reload_requests = reload_requests
        self.last_reload = 0
        self.debounce_seconds = 1.0

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory or not event.src_path.endswith('.yml'):
            return

        current_time = time.monotonic()
        if current_time - self.last_reload < self.debounce_seconds:
            return

        self.last_reload = current_time
        self.reload_requests.put(event.src_path)


def drain_reload_requests(reload_requests: queue.SimpleQueue) -> list[str]:
    changed_paths = []
    while True:
        try:
            changed_paths.append(reload_requests.get_nowait())
        except queue.Empty:
            return changed_paths


def ensure_default_config():
    """Ensure default config directory exists with at least one sample profile."""
    if not DEFAULT_CONFIG_DIR.exists():
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Created default config directory: {DEFAULT_CONFIG_DIR}")

    yml_files = list(DEFAULT_CONFIG_DIR.glob('*.yml'))
    if not yml_files:
        sample_profile_path = DEFAULT_CONFIG_DIR / "sample_profile.yml"
        sample_yml = """device: "Sample Device"
version: '1'
bindings:
  KEY_UP:
    up:
      - notify-send 'Macropad' 'Welcome! Edit this profile in ~/.config/macropad/profiles/'
"""
        sample_profile_path.write_text(sample_yml)
        print(f"Created sample profile: {sample_profile_path}")
        print(f"Edit your profiles in: {DEFAULT_CONFIG_DIR}")
        print("Run 'macropad detect --generate-profile' to create a profile for your device.")


def get_profile_paths(args: argparse.Namespace) -> List[str]:
    all_profile_paths = list(args.profile_paths) if args.profile_paths else []

    if args.profile_directories:
        for directory in args.profile_directories:
            dir_path = pathlib.Path(directory)
            if not dir_path.exists():
                print(f"Warning: Directory '{directory}' does not exist. Skipping...")
                continue
            if not dir_path.is_dir():
                print(f"Warning: '{directory}' is not a directory. Skipping...")
                continue

            yml_files = sorted(dir_path.glob('*.yml'))
            all_profile_paths.extend(str(f) for f in yml_files)

    return all_profile_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Turn every keyboard into a Macropad')
    subparsers = parser.add_subparsers(title='Subcommands', dest='subcommand', required=True)

    detect_subparser = subparsers.add_parser('detect', help="Detects input device")
    detect_subparser.add_argument(
        '--generate-profile',
        help='Generates a profile for the given device.',
        action='store_true',
        dest='generate_profile',
    )

    listen_subparser = subparsers.add_parser('listen', help="Intercept profile device")
    listen_subparser.add_argument('profile_paths', nargs='*', help='Paths to your macropad profiles.')
    listen_subparser.add_argument(
        '--directory', '-d',
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


def reload_profiles(profile_supervisor: ProfileSupervisor, args: argparse.Namespace) -> bool:
    print("Reloading profiles...")
    profile_paths = get_profile_paths(args)
    try:
        profile_supervisor.reload(profile_paths)
    except Exception as error:
        print(f"Reload aborted: {error}")
        utils.send_notification(
            title="Macropad Configuration Error",
            message=f"Configuration reload failed: {error}",
        )
        return False

    worker_count = len(profile_supervisor.workers)
    print(f"Reloaded {worker_count} profile(s)")
    utils.send_notification(
        title="Macropad Configuration Updated",
        message=f"Successfully reloaded {worker_count} profile(s)",
    )
    return True


def main():
    signal.signal(signal.SIGCHLD, utils.reap_zombie_processes)
    observer = None
    reload_requests = queue.SimpleQueue()
    profile_supervisor = ProfileSupervisor()

    try:
        args = parse_args()
        if args.subcommand == 'listen':
            notify2.init('Macropad')

            using_default_config = False
            if not args.profile_paths and not args.profile_directories:
                ensure_default_config()
                args.profile_directories = [str(DEFAULT_CONFIG_DIR)]
                using_default_config = True

            all_profile_paths = get_profile_paths(args)

            if not all_profile_paths:
                print("Error: No profile files found. Please add profile files to your directories.")
                return

            try:
                profile_supervisor.start(all_profile_paths)
            except Exception as error:
                print(f"Error loading profiles: {error}")
                return

            enable_watch = args.watch or using_default_config
            if enable_watch:
                if not args.profile_directories:
                    print("Warning: --watch flag requires --directory to be specified. Watch mode disabled.")
                else:
                    observer = PollingObserver()
                    event_handler = ProfileReloadHandler(reload_requests)

                    for directory in args.profile_directories:
                        dir_path = pathlib.Path(directory)
                        if dir_path.exists() and dir_path.is_dir():
                            observer.schedule(event_handler, str(dir_path), recursive=False)
                            print(f"Watching directory: {dir_path}")

                    try:
                        observer.start()
                        print("Watch mode enabled. Profiles will auto-reload on changes (including symlinks).")
                    except Exception as e:
                        print(f"Error starting observer: {e}")
                        observer = None

            if observer and observer.is_alive():
                try:
                    while True:
                        time.sleep(1)
                        changed_paths = drain_reload_requests(reload_requests)
                        if changed_paths:
                            print(f"Profile changes detected: {', '.join(changed_paths)}")
                            reload_profiles(profile_supervisor, args)
                            continue
                        failed_workers = profile_supervisor.failed_workers()
                        if failed_workers:
                            print(f"Process {failed_workers[0].process.pid} died, reloading...")
                            reload_profiles(profile_supervisor, args)
                except KeyboardInterrupt:
                    pass
            else:
                profile_supervisor.join()

        elif args.subcommand == 'detect':
            detect(args)
    except KeyboardInterrupt:
        print('Keyboard interrupt. Exiting . . .')
    except OSError as e:
        if e.errno == 19:
            print('Device lost. Exiting . . .')
    finally:
        if observer and observer.is_alive():
            observer.stop()
            observer.join()
        profile_supervisor.shutdown()


def detect(args: argparse.Namespace):
    device = interceptor.detect()
    if not args.generate_profile:
        return

    profile_yml = profiles.create_sample(device).dump()
    print('----------- Profile -----------')
    print(profile_yml)
    print('-------------------------------')

    ensure_default_config()
    filename = DEFAULT_CONFIG_DIR / 'profile.yml'
    counter = 0
    while filename.exists():
        counter += 1
        filename = DEFAULT_CONFIG_DIR / f"profile_{counter}.yml"

    filename.write_text(profile_yml)
    print(f'Sample profile generated in {filename}')


if __name__ == '__main__':
    main()
