import tempfile
import unittest
from pathlib import Path

from macropad.cli import profile_files


class DefaultConfigDirectoryTests(unittest.TestCase):
    def test_unset_xdg_config_home_uses_standard_default(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            home = Path(temp_directory) / 'home'

            config_directory = profile_files.resolve_default_config_directory({}, home)

        self.assertEqual(home / '.config' / 'macropad' / 'profiles', config_directory)

    def test_absolute_xdg_config_home_is_used(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            home = root / 'home'
            xdg_config_home = root / 'config'

            config_directory = profile_files.resolve_default_config_directory(
                {'XDG_CONFIG_HOME': str(xdg_config_home)},
                home,
            )

        self.assertEqual(xdg_config_home / 'macropad' / 'profiles', config_directory)

    def test_relative_xdg_config_home_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            home = Path(temp_directory) / 'home'

            config_directory = profile_files.resolve_default_config_directory(
                {'XDG_CONFIG_HOME': 'relative/config'},
                home,
            )

        self.assertEqual(home / '.config' / 'macropad' / 'profiles', config_directory)

    def test_existing_legacy_directory_is_used_until_xdg_directory_exists(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            home = root / 'home'
            legacy_directory = home / '.config' / 'macropad' / 'profiles'
            legacy_directory.mkdir(parents=True)
            xdg_config_home = root / 'config'

            config_directory = profile_files.resolve_default_config_directory(
                {'XDG_CONFIG_HOME': str(xdg_config_home)},
                home,
            )

        self.assertEqual(legacy_directory, config_directory)

    def test_existing_xdg_directory_takes_precedence_over_legacy_directory(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            home = root / 'home'
            legacy_directory = home / '.config' / 'macropad' / 'profiles'
            legacy_directory.mkdir(parents=True)
            xdg_directory = root / 'config' / 'macropad' / 'profiles'
            xdg_directory.mkdir(parents=True)

            config_directory = profile_files.resolve_default_config_directory(
                {'XDG_CONFIG_HOME': str(root / 'config')},
                home,
            )

        self.assertEqual(xdg_directory, config_directory)


if __name__ == '__main__':
    unittest.main()
