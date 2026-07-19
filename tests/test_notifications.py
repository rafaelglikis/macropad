import unittest
from unittest.mock import patch

from macropad import notifications


class NotificationTests(unittest.TestCase):
    def test_backend_rejection_is_reported_as_unavailable(self):
        with patch('macropad.notifications.notify2.init', return_value=False):
            error = notifications.check_availability()

        self.assertEqual('notification backend did not initialize', error)

    def test_initialization_failure_is_nonfatal(self):
        with (
            patch(
                'macropad.notifications.notify2.init',
                side_effect=RuntimeError('session bus unavailable'),
            ),
            patch('macropad.notifications.logger') as logger,
        ):
            notifications.initialize()

        logger.warning.assert_called_once_with(
            'notification initialization failed; continuing without notifications',
            extra={'error': 'session bus unavailable'},
        )

    def test_send_failure_is_nonfatal(self):
        with (
            patch(
                'macropad.notifications.notify2.Notification',
                side_effect=RuntimeError('notification service unavailable'),
            ),
            patch('macropad.notifications.logger') as logger,
        ):
            notifications.send('Title', 'Message')

        logger.warning.assert_called_once_with(
            'notification failed',
            extra={'error': 'notification service unavailable'},
        )


if __name__ == '__main__':
    unittest.main()
