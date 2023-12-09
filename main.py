# PYTHON_ARGCOMPLETE_OK
import argparse
import pathlib

import argcomplete

import interceptor
import profile
import tray
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
    listen_subparser.add_argument('profile_path', help='Path to your macropad profile.')

    args = parser.parse_args()
    argcomplete.autocomplete(parser)

    return args


def main():
    try:
        args = parse_args()
        if args.subcommand == 'listen':
            tray.create()
            listen(profile.create_from_yml(args.profile_path))
        if args.subcommand == 'detect':
            detect(args)
    except KeyboardInterrupt:
        print('Keyboard interrupt. Exiting . . .')
    except OSError as e:
        if e.errno == 19:
            print('Device lost. Exiting . . .')


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
