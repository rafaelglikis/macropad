import subprocess
import tempfile
from pathlib import Path

from macropad import service_unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    executable = PROJECT_ROOT / '.venv/bin/macropad'
    rendered = service_unit.render_unit(executable)
    if not rendered.startswith(service_unit.GENERATED_MARKER):
        raise RuntimeError('rendered unit is missing its ownership marker')
    if 'WorkingDirectory=' in rendered:
        raise RuntimeError('installed service must not depend on a source checkout')

    with tempfile.TemporaryDirectory(prefix='macropad-systemd-') as temp_directory:
        unit_path = Path(temp_directory) / service_unit.SERVICE_NAME
        unit_path.write_text(rendered, encoding='utf-8')
        completed = subprocess.run(
            ['systemd-analyze', '--user', 'verify', str(unit_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(
                f'systemd unit validation failed:\n{completed.stdout}{completed.stderr}'
            )

    print(f'verified installed service unit for: {executable}')


if __name__ == '__main__':
    main()
