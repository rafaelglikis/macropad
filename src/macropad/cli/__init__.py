# PYTHON_ARGCOMPLETE_OK
import argparse
import errno
import logging

import argcomplete

from ..logging_config import configure_logging
from . import doctor, listen, service, validate

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Turn every keyboard into a Macropad')
    subparsers = parser.add_subparsers(title='Subcommands', dest='subcommand', required=True)

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

    subparsers.add_parser(
        'doctor',
        help='Check input permissions and runtime environment',
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

    service_subparser = subparsers.add_parser(
        'service',
        help='Manage the systemd user service',
    )
    service_subparsers = service_subparser.add_subparsers(
        title='Service actions',
        dest='service_action',
        required=True,
    )
    service_action_help = {
        'enable': 'Enable the service at login',
        'disable': 'Disable the service at login',
        'start': 'Start the service',
        'stop': 'Stop the service',
        'restart': 'Restart the service',
        'status': 'Show service status',
        'logs': 'Follow service logs',
    }
    for action in service.SERVICE_ACTIONS:
        service_subparsers.add_parser(action, help=service_action_help[action])

    argcomplete.autocomplete(parser)
    return parser.parse_args()


def main() -> int:
    configure_logging()
    try:
        args = parse_args()
        if args.subcommand == 'doctor':
            return doctor.run()
        if args.subcommand == 'service':
            return service.run(args.service_action)
        if args.subcommand == 'listen':
            return listen.run(args)
        return validate.run(args)
    except KeyboardInterrupt:
        logger.info('keyboard interrupt received; exiting')
    except OSError as error:
        if error.errno == errno.ENODEV:
            logger.warning('input device lost; exiting', extra={'error': str(error)})
        else:
            logger.exception('operating system error; exiting', extra={'error': str(error)})
            return 1

    return 0
