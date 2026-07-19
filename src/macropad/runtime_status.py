import errno
import fcntl
import json
import os
import socket
import stat
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

SOCKET_NAME = 'status.sock'
LOCK_NAME = 'status.lock'
MAX_RESPONSE_BYTES = 1024 * 1024


class RuntimeStatusUnavailable(ConnectionError):
    pass


def get_runtime_directory(
    environ: Mapping[str, str] | None = None,
    uid: int | None = None,
) -> Path:
    environ = os.environ if environ is None else environ
    uid = os.getuid() if uid is None else uid
    xdg_runtime_dir = environ.get('XDG_RUNTIME_DIR')
    if xdg_runtime_dir and Path(xdg_runtime_dir).is_absolute():
        return Path(xdg_runtime_dir) / 'macropad'
    return Path(tempfile.gettempdir()) / f'macropad-{uid}'


def get_socket_path(
    environ: Mapping[str, str] | None = None,
    uid: int | None = None,
) -> Path:
    return get_runtime_directory(environ, uid) / SOCKET_NAME


def _prepare_runtime_directory(directory: Path) -> None:
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = directory.lstat()
    except OSError as error:
        raise RuntimeError(f'could not prepare runtime directory {directory}: {error}') from error
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise RuntimeError(f'runtime path is not a directory: {directory}')
    if directory_stat.st_uid != os.getuid():
        raise RuntimeError(f'runtime directory is not owned by the current user: {directory}')
    directory.chmod(0o700)


def _acquire_runtime_lock(path: Path):
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise RuntimeError(f'could not open runtime status lock {path}: {error}') from error
    try:
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.getuid():
            raise RuntimeError(f'runtime status lock is not a user-owned file: {path}')
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise RuntimeError('another Macropad listener is already running') from error
    except BaseException:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, 'r+b')


def _unlink_socket_if_same(path: Path, expected_stat) -> bool:
    try:
        current_stat = path.lstat()
    except FileNotFoundError:
        return True
    if (
        stat.S_ISSOCK(current_stat.st_mode)
        and current_stat.st_dev == expected_stat.st_dev
        and current_stat.st_ino == expected_stat.st_ino
    ):
        path.unlink()
        return True
    return False


def _remove_stale_socket(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(path_stat.st_mode):
        raise RuntimeError(f'runtime status path is not a socket: {path}')

    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
    except OSError as error:
        if error.errno not in (errno.ECONNREFUSED, errno.ENOENT):
            raise RuntimeError(
                f'could not inspect runtime status socket {path}: {error}'
            ) from error
    else:
        raise RuntimeError('another Macropad listener is already running')
    finally:
        probe.close()
    if not _unlink_socket_if_same(path, path_stat):
        raise RuntimeError(f'runtime status socket changed during stale cleanup: {path}')


class RuntimeStatusServer:
    def __init__(self, socket_path: Path | None = None):
        self.socket_path = socket_path or get_socket_path()
        _prepare_runtime_directory(self.socket_path.parent)
        self._lock_file = _acquire_runtime_lock(self.socket_path.parent / LOCK_NAME)
        self._socket = None
        self._socket_stat = None
        self._shutdown = threading.Event()
        self._response_lock = threading.Lock()
        self._response = (
            json.dumps(
                {'pid': os.getpid(), 'configuration_error': None, 'workers': []},
                separators=(',', ':'),
            ).encode('utf-8')
            + b'\n'
        )
        self._thread = None
        try:
            _remove_stale_socket(self.socket_path)
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.bind(str(self.socket_path))
            self._socket_stat = self.socket_path.lstat()
            self.socket_path.chmod(0o600)
            self._socket.listen()
            self._socket.settimeout(0.1)
            self._thread = threading.Thread(
                target=self._serve,
                name='macropad-runtime-status',
                daemon=True,
            )
            self._thread.start()
        except BaseException:
            if self._socket is not None:
                self._socket.close()
            if self._socket_stat is not None:
                _unlink_socket_if_same(self.socket_path, self._socket_stat)
            self._lock_file.close()
            raise

    def poll(self, status: dict) -> None:
        self.publish(status)

    def publish(self, status: dict) -> None:
        response = json.dumps(status, separators=(',', ':')).encode('utf-8') + b'\n'
        with self._response_lock:
            self._response = response

    def _serve(self) -> None:
        while not self._shutdown.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(0.2)
                try:
                    with self._response_lock:
                        response = self._response
                    connection.sendall(response)
                except OSError:
                    pass

    def close(self) -> None:
        if self._socket is None:
            return
        self._shutdown.set()
        self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._socket_stat is not None:
            _unlink_socket_if_same(self.socket_path, self._socket_stat)
        self._lock_file.close()
        self._socket = None


def request_status(socket_path: Path | None = None, timeout: float = 2.0) -> dict:
    socket_path = socket_path or get_socket_path()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        response = bytearray()
        while chunk := client.recv(65536):
            response.extend(chunk)
            if len(response) > MAX_RESPONSE_BYTES:
                raise RuntimeStatusUnavailable('runtime status response is too large')
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout) as error:
        raise RuntimeStatusUnavailable(f'could not reach the Macropad listener: {error}') from error
    except OSError as error:
        raise RuntimeStatusUnavailable(f'could not read runtime status: {error}') from error
    finally:
        client.close()

    try:
        status = json.loads(response)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeStatusUnavailable('the listener returned invalid runtime status') from error
    if not isinstance(status, dict):
        raise RuntimeStatusUnavailable('the listener returned invalid runtime status')
    return status
