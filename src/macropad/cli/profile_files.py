import argparse
import logging
import os
import pathlib
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def resolve_default_config_directory(
    environ: Mapping[str, str] | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    environ = os.environ if environ is None else environ
    home = pathlib.Path.home() if home is None else home
    legacy_directory = home / '.config' / 'macropad' / 'profiles'

    xdg_config_home = environ.get('XDG_CONFIG_HOME')
    if not xdg_config_home:
        return legacy_directory

    xdg_config_home_path = pathlib.Path(xdg_config_home)
    if not xdg_config_home_path.is_absolute():
        return legacy_directory

    xdg_directory = xdg_config_home_path / 'macropad' / 'profiles'
    if xdg_directory.exists() or not legacy_directory.exists():
        return xdg_directory
    return legacy_directory


DEFAULT_CONFIG_DIR = resolve_default_config_directory()


def get_profile_paths(args: argparse.Namespace) -> list[str]:
    all_profile_paths = list(args.profile_paths) if args.profile_paths else []

    if args.profile_directories:
        for directory in args.profile_directories:
            dir_path = pathlib.Path(directory)
            if not dir_path.exists():
                logger.warning(
                    'profile directory does not exist; skipping', extra={'path': directory}
                )
                continue
            if not dir_path.is_dir():
                logger.warning(
                    'profile path is not a directory; skipping', extra={'path': directory}
                )
                continue

            yml_files = sorted(dir_path.glob('*.yml'))
            all_profile_paths.extend(str(profile) for profile in yml_files)

    unique_profile_paths = []
    seen_paths = set()
    for profile_path in all_profile_paths:
        canonical_path = pathlib.Path(profile_path).expanduser().resolve(strict=False)
        if canonical_path in seen_paths:
            continue
        seen_paths.add(canonical_path)
        unique_profile_paths.append(profile_path)
    return unique_profile_paths
