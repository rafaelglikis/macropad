import argparse
import logging
import pathlib

logger = logging.getLogger(__name__)
DEFAULT_CONFIG_DIR = pathlib.Path.home() / '.config' / 'macropad' / 'profiles'


def ensure_default_config() -> None:
    if not DEFAULT_CONFIG_DIR.exists():
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            'default configuration directory created',
            extra={'path': str(DEFAULT_CONFIG_DIR)},
        )

    yml_files = list(DEFAULT_CONFIG_DIR.glob('*.yml'))
    if not yml_files:
        sample_profile_path = DEFAULT_CONFIG_DIR / 'sample_profile.yml'
        sample_yml = """device: "Sample Device"
version: '1'
bindings:
  KEY_UP:
    up:
      - notify-send 'Macropad' 'Welcome! Edit this profile in ~/.config/macropad/profiles/'
"""
        sample_profile_path.write_text(sample_yml)
        logger.info('sample profile created', extra={'path': str(sample_profile_path)})
        logger.info(
            'edit profiles in configuration directory', extra={'path': str(DEFAULT_CONFIG_DIR)}
        )
        logger.info("run 'macropad detect --generate-profile' to create a device profile")


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
