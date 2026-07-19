import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STARTUP_MESSAGE = 'profile watch mode enabled'
RELOAD_MESSAGE = 'profiles reloaded'
PROFILE = """device: "Macropad CI Missing Device"
version: '1'
bindings:
  KEY_A:
    up: 'true'
"""
UPDATED_PROFILE = """device: "Macropad CI Missing Device"
version: '1'
bindings:
  KEY_B:
    up: 'true'
"""


def read_stderr(stream, lines: queue.Queue, output: list[str]) -> None:
    for line in stream:
        output.append(line)
        lines.put(line)


def wait_for_message(
    process: subprocess.Popen,
    lines: queue.Queue,
    output: list[str],
    message: str,
    description: str,
) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if message in line:
            return
    if any(message in line for line in output):
        return
    raise RuntimeError(description)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='macropad-service-') as temp_dir:
        temp_path = Path(temp_dir)
        profile_directory = temp_path / 'profiles'
        profile_directory.mkdir()
        profile_path = profile_directory / 'ci.yml'
        profile_path.write_text(PROFILE)

        environment = os.environ.copy()
        environment['HOME'] = str(temp_path / 'home')
        environment.pop('DBUS_SESSION_BUS_ADDRESS', None)
        environment.pop('DISPLAY', None)
        environment.pop('WAYLAND_DISPLAY', None)
        process = subprocess.Popen(
            [
                str(PROJECT_ROOT / '.venv/bin/macropad'),
                '--verbose',
                'listen',
                '--watch',
                '--directory',
                str(profile_directory),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        lines = queue.Queue()
        output = []
        reader = threading.Thread(
            target=read_stderr,
            args=(process.stderr, lines, output),
            daemon=True,
        )
        reader.start()

        try:
            wait_for_message(
                process,
                lines,
                output,
                STARTUP_MESSAGE,
                'service did not become ready before timeout',
            )

            replacement_path = profile_directory / '.ci.yml.tmp'
            replacement_path.write_text(UPDATED_PROFILE)
            os.replace(replacement_path, profile_path)
            wait_for_message(
                process,
                lines,
                output,
                RELOAD_MESSAGE,
                'service did not reload an atomically replaced profile',
            )

            process.terminate()
            return_code = process.wait(timeout=10)
            if return_code != 0:
                raise RuntimeError(f'service exited with status {return_code}')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            reader.join(timeout=1)

        print('verified service startup, atomic reload, and graceful shutdown')


if __name__ == '__main__':
    main()
