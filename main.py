# PYTHON_ARGCOMPLETE_OK
import argparse
import multiprocessing
import pathlib
import signal

import argcomplete

import interceptor
import profile
import utils
from interceptor import listen


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
    args = parser.parse_args()
    argcomplete.autocomplete(parser)

    return args


def main():
    processes = []
    signal.signal(signal.SIGCHLD, utils.reap_zombie_processes)
    try:
        args = parse_args()
        if args.subcommand == 'listen':
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

            if not all_profile_paths:
                print("Error: No profile paths or directories specified.")
                return

            for profile_path in all_profile_paths:
                profile_obj = profile.create_from_yml(profile_path)
                process = multiprocessing.Process(target=listen, args=(profile_obj,))
                process.start()
                processes.append(process)

            for process in processes:
                process.join()

        elif args.subcommand == 'detect':
            detect(args)
    except KeyboardInterrupt:
        print('Keyboard interrupt. Exiting . . .')
        for process in processes:
            process.terminate()
            process.join()
    except OSError as e:
        if e.errno == 19:
            print('Device lost. Exiting . . .')
            for process in processes:
                process.terminate()
                process.join()


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
