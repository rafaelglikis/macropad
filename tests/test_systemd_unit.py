import unittest
from pathlib import Path

from tools.render_systemd_unit import TEMPLATE_PATH, render_service

TEMPLATE = """[Service]
WorkingDirectory=@WORKING_DIRECTORY@
ExecStart=@EXECUTABLE@ listen --watch
"""


class SystemdUnitRendererTests(unittest.TestCase):
    def test_project_path_is_rendered_without_shell_interpretation(self):
        project_root = Path('/tmp/macropad & tools|$(touch marker)%build')

        rendered = render_service(TEMPLATE, project_root)

        self.assertIn(
            'WorkingDirectory=/tmp/macropad & tools|$(touch marker)%%build',
            rendered,
        )
        self.assertIn(
            'ExecStart="/tmp/macropad & tools|$$(touch marker)%%build/'
            '.venv/bin/macropad" listen --watch',
            rendered,
        )

    def test_control_characters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'control characters'):
            render_service(TEMPLATE, Path('/tmp/macropad\ninvalid'))

    def test_service_path_includes_standard_user_command_directories(self):
        rendered = render_service(TEMPLATE_PATH.read_text(), Path('/tmp/macropad'))

        self.assertIn(
            'Environment=PATH=%h/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin:'
            '/usr/local/sbin:/usr/sbin:/sbin',
            rendered,
        )


if __name__ == '__main__':
    unittest.main()
