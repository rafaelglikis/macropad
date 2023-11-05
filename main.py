# PYTHON_ARGCOMPLETE_OK
import argparse
import argcomplete
from Profile import Profile
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
        listen(Profile(args.profile))
    except KeyboardInterrupt:
        print('Keyboard interrupt exiting.')
        return


if __name__ == '__main__':
    main()
