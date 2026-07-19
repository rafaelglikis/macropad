import os
import shlex
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        output = completed.stdout + completed.stderr
        raise RuntimeError(f'command failed: {shlex.join(command)}\n{output}')
    return completed


def main() -> None:
    clean_env = os.environ.copy()
    clean_env.pop('PYTHONPATH', None)
    clean_env.pop('VIRTUAL_ENV', None)
    clean_env['PYTHONNOUSERSITE'] = '1'

    with tempfile.TemporaryDirectory(prefix='macropad-wheel-') as temp_dir:
        temp_path = Path(temp_dir)
        dist_path = temp_path / 'dist'
        environment_path = temp_path / 'environment'
        work_path = temp_path / 'work'
        work_path.mkdir()

        run(
            ['uv', 'build', '--out-dir', str(dist_path)],
            PROJECT_ROOT,
            clean_env,
        )
        source_archives = list(dist_path.glob('macropad-*.tar.gz'))
        if len(source_archives) != 1:
            raise RuntimeError(f'expected one source archive, found {len(source_archives)}')
        wheels = list(dist_path.glob('macropad-*.whl'))
        if len(wheels) != 1:
            raise RuntimeError(f'expected one wheel, found {len(wheels)}')
        wheel_path = wheels[0]

        with zipfile.ZipFile(wheel_path) as wheel:
            members = set(wheel.namelist())
            required_members = {
                'macropad/__init__.py',
                'macropad/__main__.py',
                'macropad/assets/macropad.svg',
                'macropad/cli/__init__.py',
                'macropad/cli/doctor.py',
                'macropad/cli/listen.py',
                'macropad/cli/monitor.py',
                'macropad/cli/profile_files.py',
                'macropad/cli/service.py',
                'macropad/cli/validate.py',
                'macropad/diagnostics.py',
            }
            missing_members = required_members - members
            if missing_members:
                raise RuntimeError(f'wheel is missing: {sorted(missing_members)}')

            entry_point_files = [
                member for member in members if member.endswith('.dist-info/entry_points.txt')
            ]
            if len(entry_point_files) != 1:
                raise RuntimeError('wheel must contain one entry_points.txt file')
            entry_points = wheel.read(entry_point_files[0]).decode()
            if 'macropad = macropad.cli:main' not in entry_points:
                raise RuntimeError('wheel does not declare the macropad console command')

            license_files = [
                member for member in members if member.endswith('.dist-info/licenses/LICENSE')
            ]
            if len(license_files) != 1:
                raise RuntimeError('wheel must contain one MIT license file')

            metadata_files = [
                member for member in members if member.endswith('.dist-info/METADATA')
            ]
            if len(metadata_files) != 1:
                raise RuntimeError('wheel must contain one METADATA file')
            metadata = Parser().parsestr(wheel.read(metadata_files[0]).decode())
            if metadata['License-Expression'] != 'MIT':
                raise RuntimeError('wheel does not declare the MIT license')
            if metadata['Description-Content-Type'] != 'text/markdown':
                raise RuntimeError('wheel does not use README.md as its description')
            project_urls = metadata.get_all('Project-URL', [])
            if 'Repository, https://github.com/rafaelglikis/macropad' not in project_urls:
                raise RuntimeError('wheel does not declare the repository URL')

        run(
            ['uv', 'venv', '--python', sys.executable, str(environment_path)],
            PROJECT_ROOT,
            clean_env,
        )
        python_path = environment_path / 'bin/python'
        console_path = environment_path / 'bin/macropad'
        run(
            ['uv', 'pip', 'install', '--python', str(python_path), str(wheel_path)],
            work_path,
            clean_env,
        )

        console_help = run([str(console_path), '--help'], work_path, clean_env)
        module_help = run(
            [str(python_path), '-m', 'macropad', '--help'],
            work_path,
            clean_env,
        )
        for help_output in (console_help.stdout, module_help.stdout):
            if 'Turn every keyboard into a Macropad' not in help_output:
                raise RuntimeError('installed entry point did not show macropad help')

        installed_package = run(
            [
                str(python_path),
                '-c',
                (
                    'from importlib.resources import files; '
                    'from pathlib import Path; '
                    'import macropad; '
                    "asset = files('macropad').joinpath('assets/macropad.svg'); "
                    'assert asset.is_file(); '
                    'print(Path(macropad.__file__).resolve())'
                ),
            ],
            work_path,
            clean_env,
        )
        package_path = Path(installed_package.stdout.strip())
        if package_path == PROJECT_ROOT or PROJECT_ROOT in package_path.parents:
            raise RuntimeError('smoke test imported macropad from the source checkout')

        print(f'verified wheel: {wheel_path.name}')


if __name__ == '__main__':
    main()
