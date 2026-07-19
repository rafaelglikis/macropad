import argparse
import logging

from .. import validation
from . import profile_files

logger = logging.getLogger(__name__)


def run(args: argparse.Namespace) -> int:
    if not args.profile_paths and not args.profile_directories:
        args.profile_directories = [str(profile_files.DEFAULT_CONFIG_DIR)]

    profile_paths = profile_files.get_profile_paths(args)
    if not profile_paths:
        logger.error('no profile files found')
        return 1
    return validation.run(profile_paths)
