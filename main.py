# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete

import interceptor
import profile
from interceptor import listen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Turn every keyboard into a Macropad')
    subparsers = parser.add_subparsers(title='Subcommands', dest='subcommand', required=True)

    subparsers.add_parser('detect', help="Detects input device")

    listen_subparser = subparsers.add_parser('listen', help="Intercept profile device")
    listen_subparser.add_argument('profile_path', help='Path to your macropad profile.')

    args = parser.parse_args()
    argcomplete.autocomplete(parser)

    return args


def main():
    try:
        args = parse_args()
        if args.subcommand == 'detect':
            interceptor.detect()
        if args.subcommand == 'listen':
            listen(profile.create_from_yml(args.profile_path))
    except KeyboardInterrupt:
        print('Keyboard interrupt exiting.')
        return


if __name__ == '__main__':
    main()
