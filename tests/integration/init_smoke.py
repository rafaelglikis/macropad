import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from macropad import diagnostics, interceptor, profiles
from macropad.cli import init as init_command
from macropad.cli import profile_files, service


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='macropad-init-') as temp_directory:
        root = Path(temp_directory)
        profile_directory = profile_files.resolve_default_config_directory(
            {'XDG_CONFIG_HOME': str(root / 'config')},
            root / 'home',
        )
        input_ready = [
            diagnostics.DiagnosticResult(
                diagnostics.PASS,
                'Input devices',
                'Input access is ready.',
            )
        ]
        detected = interceptor.DetectedInput(
            'Macropad Integration Keyboard',
            'KEY_A',
            '/dev/input/event99',
        )

        with (
            patch.object(profile_files, 'DEFAULT_CONFIG_DIR', profile_directory),
            patch(
                'macropad.cli.init.diagnostics.check_input_devices',
                return_value=input_ready,
            ),
            patch(
                'macropad.cli.init.service.get_info',
                return_value=service.ServiceInfo(None, False, 'not installed'),
            ),
            patch('macropad.cli.init.interceptor.detect', return_value=detected),
            patch('builtins.input', side_effect=['', 'echo integration']),
            redirect_stdout(io.StringIO()),
        ):
            exit_status = init_command.run(SimpleNamespace(timeout=5.0))

        profile_paths = sorted(profile_directory.glob('*.yml'))
        if exit_status != 0 or len(profile_paths) != 1:
            raise RuntimeError('guided initialization did not create exactly one profile')
        prepared_profiles = profiles.prepare_profiles([str(profile_paths[0])])
        if prepared_profiles[0].device_name != detected.device_name:
            raise RuntimeError('generated profile has the wrong device name')

        print(f'verified guided initialization: {profile_paths[0]}')


if __name__ == '__main__':
    main()
