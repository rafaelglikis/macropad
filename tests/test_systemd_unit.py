import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macropad import service_unit


class SystemdUnitRendererTests(unittest.TestCase):
    def test_installed_executable_is_rendered_without_shell_interpretation(self):
        executable = Path('/tmp/macropad & tools|$(touch marker)%build/bin/macropad')

        rendered = service_unit.render_unit(executable)

        self.assertTrue(rendered.startswith(service_unit.GENERATED_MARKER))
        self.assertIn(
            'ExecStart="/tmp/macropad & tools|$$(touch marker)%%build/bin/macropad" '
            '--verbose listen --watch',
            rendered,
        )
        self.assertNotIn('WorkingDirectory=', rendered)

    def test_control_characters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'control characters'):
            service_unit.render_unit(Path('/tmp/macropad\ninvalid'))

    def test_service_path_includes_standard_user_command_directories(self):
        rendered = service_unit.render_unit(Path('/opt/macropad/bin/macropad'))

        self.assertIn(f'Environment="PATH={service_unit.ACTION_PATH}"', rendered)

    def test_service_runs_with_the_graphical_session(self):
        rendered = service_unit.render_unit(Path('/opt/macropad/bin/macropad'))

        self.assertIn('After=graphical-session.target', rendered)
        self.assertIn('PartOf=graphical-session.target', rendered)
        self.assertIn('WantedBy=graphical-session.target', rendered)
        self.assertNotIn('default.target', rendered)

    def test_custom_action_path_is_normalized_and_safely_rendered(self):
        rendered = service_unit.render_unit(
            Path('/opt/macropad/bin/macropad'),
            action_path='/opt/My Tools/%build:/usr/bin:/opt/My Tools/%build',
        )

        self.assertIn('Environment="PATH=/opt/My Tools/%%build:/usr/bin"', rendered)

    def test_custom_action_path_requires_nonempty_absolute_entries(self):
        invalid_paths = ('', '/usr/bin:', 'relative:/usr/bin', '%h/bin:/usr/bin')

        for action_path in invalid_paths:
            with self.subTest(action_path=action_path), self.assertRaises(ValueError):
                service_unit.render_unit(
                    Path('/opt/macropad/bin/macropad'),
                    action_path=action_path,
                )

    def test_disabled_notifications_are_persisted_in_service_command(self):
        rendered = service_unit.render_unit(
            Path('/opt/macropad/bin/macropad'),
            notifications_enabled=False,
        )

        self.assertIn(
            'ExecStart="/opt/macropad/bin/macropad" --no-notifications --verbose listen --watch',
            rendered,
        )


class SystemdUnitFileTests(unittest.TestCase):
    def test_absolute_xdg_config_home_resolves_user_unit_path(self):
        path = service_unit.resolve_unit_path(
            {'XDG_CONFIG_HOME': '/tmp/config'},
            Path('/home/demo'),
        )

        self.assertEqual(Path('/tmp/config/systemd/user/macropad.service'), path)

    def test_relative_xdg_config_home_uses_standard_user_unit_path(self):
        path = service_unit.resolve_unit_path(
            {'XDG_CONFIG_HOME': 'relative/config'},
            Path('/home/demo'),
        )

        self.assertEqual(Path('/home/demo/.config/systemd/user/macropad.service'), path)

    def test_install_refuses_unknown_unit_without_force(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / 'macropad.service'
            path.write_text('[Unit]\nDescription=Custom\n', encoding='utf-8')

            with self.assertRaisesRegex(service_unit.UnitOwnershipError, '--force'):
                service_unit.install_unit(path, 'replacement')

            self.assertEqual('[Unit]\nDescription=Custom\n', path.read_text(encoding='utf-8'))

    def test_force_install_replaces_unknown_unit_atomically(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / 'systemd/user/macropad.service'

            service_unit.install_unit(path, f'{service_unit.GENERATED_MARKER}\nunit', force=True)

            self.assertEqual(
                f'{service_unit.GENERATED_MARKER}\nunit',
                path.read_text(encoding='utf-8'),
            )
            self.assertEqual(0o644, path.stat().st_mode & 0o777)

    def test_remove_only_deletes_generated_unit(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            path = Path(temp_directory) / 'macropad.service'
            path.write_text(f'{service_unit.GENERATED_MARKER}\nunit', encoding='utf-8')

            removed = service_unit.remove_unit(path)

            self.assertTrue(removed)
            self.assertFalse(path.exists())

    def test_resolve_executable_prefers_current_python_environment(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            bin_directory = Path(temp_directory) / 'bin'
            bin_directory.mkdir()
            python = bin_directory / 'python'
            executable = bin_directory / 'macropad'
            executable.write_text('#!/bin/sh\n', encoding='utf-8')
            executable.chmod(0o755)

            resolved = service_unit.resolve_executable(str(python), path='')

        self.assertEqual(executable, resolved)

    def test_resolve_executable_falls_back_to_path(self):
        with patch('macropad.service_unit.shutil.which', return_value='/usr/bin/macropad'):
            resolved = service_unit.resolve_executable('/missing/python')

        self.assertEqual(Path('/usr/bin/macropad'), resolved)


if __name__ == '__main__':
    unittest.main()
