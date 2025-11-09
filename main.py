# PYTHON_ARGCOMPLETE_OK
import argparse
import multiprocessing
import pathlib
import signal
import time
from typing import List

import argcomplete
import notify2
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

import interceptor
import profile
import utils
from interceptor import listen

ASSETS_DIR = pathlib.Path(__file__).parent / "assets"

class ProfileReloadHandler(FileSystemEventHandler):
    def __init__(self, reload_callback):
        self.reload_callback = reload_callback
        self.last_reload = 0
        self.debounce_seconds = 1.0

    def on_any_event(self, event: FileSystemEvent):
        if event.is_directory or not event.src_path.endswith('.yml'):
            return

        current_time = time.time()
        if current_time - self.last_reload < self.debounce_seconds:
            return

        self.last_reload = current_time
        print(f"Profile change detected: {event.src_path}")
        self.reload_callback()


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


def start_profile_processes(profile_paths: List[str]) -> List[multiprocessing.Process]:
    processes = []
    for profile_path in profile_paths:
        try:
            profile_obj = profile.create_from_yml(profile_path)
            process = multiprocessing.Process(target=listen, args=(profile_obj,))
            process.start()
            processes.append(process)
            print(f"Started profile: {profile_path}")
        except Exception as e:
            print(f"Error loading profile {profile_path}: {e}")
    return processes


def stop_all_processes(processes: List[multiprocessing.Process]):
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=5)


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
    args = parser.parse_args()
    argcomplete.autocomplete(parser)

    return args


def send_notification(title: str, message: str, icon_path: str = None):
    """Send a desktop notification, gracefully handling errors."""
    try:
        notification = notify2.Notification(
            summary=title,
            message=message,
            icon=f"{ASSETS_DIR}/macropad.svg",
        )
        notification.show()
    except Exception as e:
        print(f"Notification error: {e}")


def main():
    processes = []
    signal.signal(signal.SIGCHLD, utils.reap_zombie_processes)
    observer = None

    def reload_profiles():
        nonlocal processes
        print("Reloading profiles...")
        stop_all_processes(processes)
        profile_paths = get_profile_paths(args)
        processes = start_profile_processes(profile_paths)
        print(f"Reloaded {len(processes)} profile(s)")

        send_notification(
            title="Macropad Configuration Updated",
            message=f"Successfully reloaded {len(processes)} profile(s)",
        )

    try:
        args = parse_args()
        if args.subcommand == 'listen':
            notify2.init('Macropad')
            all_profile_paths = get_profile_paths(args)

            if not all_profile_paths:
                print("Error: No profile paths or directories specified.")
                return

            processes = start_profile_processes(all_profile_paths)

            if args.watch:
                if not args.profile_directories:
                    print("Warning: --watch flag requires --directory to be specified. Watch mode disabled.")
                else:
                    observer = Observer()
                    event_handler = ProfileReloadHandler(reload_profiles)

                    for directory in args.profile_directories:
                        dir_path = pathlib.Path(directory)
                        if dir_path.exists() and dir_path.is_dir():
                            observer.schedule(event_handler, str(dir_path), recursive=False)
                            print(f"Watching directory: {dir_path}")

                    try:
                        observer.start()
                        print("Watch mode enabled. Profiles will auto-reload on changes.")
                    except Exception as e:
                        print(f"Error starting observer: {e}")
                        observer = None

            if observer and observer.is_alive():
                try:
                    while True:
                        time.sleep(1)
                        for process in processes:
                            if not process.is_alive():
                                print(f"Process {process.pid} died, reloading...")
                                reload_profiles()
                                break
                except KeyboardInterrupt:
                    pass
            else:
                for process in processes:
                    process.join()

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
        stop_all_processes(processes)


def detect(args: argparse.Namespace):
    device = interceptor.detect()
    if not args.generate_profile:
        return

    profile_yml = profile.create_sample(device).dump()
    print('----------- Profile -----------')
    print(profile_yml)
    print('-------------------------------')

    filename = 'profile.yml'
    counter = 0
    while pathlib.Path(filename).exists():
        counter += 1
        filename = f"profile_{counter}.yml"

    with open(filename, 'w') as file:
        file.write(profile_yml)
        print(f'Sample profile generated on {filename}')


if __name__ == '__main__':
    main()
