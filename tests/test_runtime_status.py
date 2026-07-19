import socket
import tempfile
import threading
import unittest
from pathlib import Path

from macropad import runtime_status


class RuntimeStatusTests(unittest.TestCase):
    def test_runtime_directory_uses_xdg_or_user_specific_fallback(self):
        self.assertEqual(
            Path('/run/user/1000/macropad'),
            runtime_status.get_runtime_directory({'XDG_RUNTIME_DIR': '/run/user/1000'}, uid=1000),
        )
        self.assertEqual(
            Path(tempfile.gettempdir()) / 'macropad-1000',
            runtime_status.get_runtime_directory({}, uid=1000),
        )

    def test_server_returns_snapshot_and_removes_socket_on_close(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'runtime' / 'status.sock'
            server = runtime_status.RuntimeStatusServer(socket_path)
            snapshot = {'pid': 123, 'configuration_error': None, 'workers': []}
            result = {}
            server.publish(snapshot)

            def request():
                result['status'] = runtime_status.request_status(socket_path)

            request_thread = threading.Thread(target=request)
            request_thread.start()
            request_thread.join(timeout=1)
            server.close()

            self.assertFalse(request_thread.is_alive())
            self.assertEqual(snapshot, result['status'])
            self.assertFalse(socket_path.exists())

    def test_inode_checked_cleanup_does_not_remove_replacement_socket(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'status.sock'
            stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            stale_socket.bind(str(socket_path))
            stale_stat = socket_path.lstat()
            stale_socket.close()
            socket_path.unlink()

            replacement_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            replacement_socket.bind(str(socket_path))
            try:
                removed = runtime_status._unlink_socket_if_same(socket_path, stale_stat)

                self.assertFalse(removed)
                self.assertTrue(socket_path.exists())
            finally:
                replacement_socket.close()
                socket_path.unlink(missing_ok=True)

    def test_active_unlocked_socket_is_not_removed(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'runtime' / 'status.sock'
            socket_path.parent.mkdir()
            active_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            active_socket.bind(str(socket_path))
            active_socket.listen()
            try:
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    runtime_status.RuntimeStatusServer(socket_path)

                self.assertTrue(socket_path.exists())
            finally:
                active_socket.close()
                socket_path.unlink(missing_ok=True)

    def test_second_server_does_not_replace_active_socket(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'runtime' / 'status.sock'
            server = runtime_status.RuntimeStatusServer(socket_path)
            try:
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    runtime_status.RuntimeStatusServer(socket_path)
            finally:
                server.close()

    def test_regular_file_is_not_removed_as_stale_socket(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'runtime' / 'status.sock'
            socket_path.parent.mkdir()
            socket_path.write_text('keep me', encoding='utf-8')

            with self.assertRaisesRegex(RuntimeError, 'not a socket'):
                runtime_status.RuntimeStatusServer(socket_path)

            self.assertEqual('keep me', socket_path.read_text(encoding='utf-8'))

    def test_missing_listener_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            socket_path = Path(temp_directory) / 'missing.sock'

            with self.assertRaises(runtime_status.RuntimeStatusUnavailable):
                runtime_status.request_status(socket_path, timeout=0.01)


if __name__ == '__main__':
    unittest.main()
