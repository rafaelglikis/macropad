# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete

import profile
from interceptor import listen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Turn every keyboard into a Macropad')
    parser.add_argument('profile', help='Path to your macropad profile.')

    args = parser.parse_args()
    argcomplete.autocomplete(parser)

    return args


def main():
    try:
        args = parse_args()
        listen(profile.create_from_yml(args.profile))
    except KeyboardInterrupt:
        print('Keyboard interrupt exiting.')
        return


if __name__ == '__main__':
    main()
