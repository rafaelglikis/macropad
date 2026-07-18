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
PROFILE = """device: "Macropad CI Missing Device"
version: '1'
bindings:
  KEY_A:
    up: 'true'
"""


def read_stderr(stream, lines: queue.Queue, output: list[str]) -> None:
    for line in stream:
        output.append(line)
        lines.put(line)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='macropad-service-') as temp_dir:
        temp_path = Path(temp_dir)
        profile_directory = temp_path / 'profiles'
        profile_directory.mkdir()
        (profile_directory / 'ci.yml').write_text(PROFILE)

        environment = os.environ.copy()
        environment['HOME'] = str(temp_path / 'home')
        environment.pop('DBUS_SESSION_BUS_ADDRESS', None)
        environment.pop('DISPLAY', None)
        environment.pop('WAYLAND_DISPLAY', None)
        process = subprocess.Popen(
            [
                str(PROJECT_ROOT / '.venv/bin/macropad'),
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
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if STARTUP_MESSAGE in line:
                    break
            else:
                raise RuntimeError('service did not become ready before timeout')

            if not any(STARTUP_MESSAGE in line for line in output):
                raise RuntimeError('service exited before startup completed')

            process.terminate()
            return_code = process.wait(timeout=10)
            if return_code != 0:
                raise RuntimeError(f'service exited with status {return_code}')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            reader.join(timeout=1)

        print('verified service startup and graceful shutdown')


if __name__ == '__main__':
    main()
