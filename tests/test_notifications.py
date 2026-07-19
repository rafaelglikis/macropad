import unittest
from unittest.mock import Mock, patch

from macropad import notifications


class NotificationTests(unittest.TestCase):
    def setUp(self):
        notifications.configure()

    def tearDown(self):
        notifications.configure()

    def test_backend_rejection_is_reported_as_unavailable(self):
        backend = Mock()
        backend.init.return_value = False

        with patch('macropad.notifications.importlib.import_module', return_value=backend):
            error = notifications.check_availability()

        self.assertEqual('notification backend did not initialize', error)

    def test_missing_dependencies_warn_once_on_repeated_sends(self):
        with (
            patch('macropad.notifications.logger') as logger,
            patch(
                'macropad.notifications.importlib.import_module',
                side_effect=ModuleNotFoundError("No module named 'notify2'"),
            ) as import_module,
        ):
            notifications.send('First', 'Message')
            notifications.send('Second', 'Message')

        import_module.assert_called_once_with('notify2')
        logger.warning.assert_called_once_with(
            'notification initialization failed; continuing without notifications',
            extra={
                'error': 'notification dependencies are not installed; '
                'install poor-mans-macropad[notifications]'
            },
        )

    def test_disabled_notifications_never_import_backend(self):
        notifications.configure(enabled=False)

        with (
            patch('macropad.notifications.logger') as logger,
            patch('macropad.notifications.importlib.import_module') as import_module,
        ):
            notifications.send('Title', 'Message')
            error = notifications.check_availability()

        self.assertEqual('disabled by --no-notifications', error)
        import_module.assert_not_called()
        logger.warning.assert_not_called()

    def test_backend_initializes_once_for_multiple_notifications(self):
        backend = Mock()
        backend.init.return_value = True

        with patch('macropad.notifications.importlib.import_module', return_value=backend):
            notifications.send('First', 'Message')
            notifications.send('Second', 'Message')

        backend.init.assert_called_once_with('Macropad')
        self.assertEqual(2, backend.Notification.call_count)
        self.assertEqual(2, backend.Notification.return_value.show.call_count)

    def test_send_failure_warns_once_and_disables_later_attempts(self):
        backend = Mock()
        backend.init.return_value = True
        backend.Notification.side_effect = RuntimeError('notification service unavailable')

        with (
            patch('macropad.notifications.logger') as logger,
            patch('macropad.notifications.importlib.import_module', return_value=backend),
        ):
            notifications.send('First', 'Message')
            notifications.send('Second', 'Message')

        backend.Notification.assert_called_once()
        logger.warning.assert_called_once_with(
            'notification failed; continuing without notifications',
            extra={'error': 'notification service unavailable'},
        )


if __name__ == '__main__':
    unittest.main()
