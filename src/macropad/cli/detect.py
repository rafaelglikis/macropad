import argparse
import logging

from .. import interceptor, profiles
from . import profile_files

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace) -> int:
    device_name = interceptor.detect()
    if not args.generate_profile:
        return 0

    profile_yml = profiles.dump_yml(profiles.create_sample(device_name))
    print('----------- Profile -----------')
    print(profile_yml)
    print('-------------------------------')

    profile_files.ensure_default_config()
    filename = profile_files.DEFAULT_CONFIG_DIR / 'profile.yml'
    counter = 0
    while filename.exists():
        counter += 1
        filename = profile_files.DEFAULT_CONFIG_DIR / f'profile_{counter}.yml'

    filename.write_text(profile_yml)
    logger.info('sample profile generated', extra={'path': str(filename)})
    return 0
