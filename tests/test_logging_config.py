import logging
import unittest
from unittest.mock import patch

from macropad.logging_config import ContextFormatter, configure_logging


class ContextFormatterTests(unittest.TestCase):
    def test_context_fields_are_appended_in_stable_order(self):
        record = logging.LogRecord(
            name='macropad.actions',
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg='action exited',
            args=(),
            exc_info=None,
        )
        record.device = 'Macro Keyboard'
        record.command = 'demo-command'
        record.exit_status = 7
        formatter = ContextFormatter('%(levelname)s %(name)s %(message)s')

        message = formatter.format(record)

        self.assertEqual(
            'WARNING macropad.actions action exited '
            "device='Macro Keyboard' command='demo-command' exit_status=7",
            message,
        )

    def test_record_without_context_uses_base_format(self):
        record = logging.LogRecord(
            name='macropad.cli',
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='profile watch mode enabled',
            args=(),
            exc_info=None,
        )
        formatter = ContextFormatter('%(levelname)s %(name)s %(message)s')

        self.assertEqual(
            'INFO macropad.cli profile watch mode enabled',
            formatter.format(record),
        )


class LoggingConfigurationTests(unittest.TestCase):
    def test_default_logging_shows_warnings(self):
        with patch('macropad.logging_config.logging.basicConfig') as basic_config:
            configure_logging()

        self.assertEqual(logging.WARNING, basic_config.call_args.kwargs['level'])

    def test_verbose_logging_shows_information(self):
        with patch('macropad.logging_config.logging.basicConfig') as basic_config:
            configure_logging(verbose=True)

        self.assertEqual(logging.INFO, basic_config.call_args.kwargs['level'])

    def test_debug_logging_takes_precedence(self):
        with patch('macropad.logging_config.logging.basicConfig') as basic_config:
            configure_logging(verbose=True, debug=True)

        self.assertEqual(logging.DEBUG, basic_config.call_args.kwargs['level'])


if __name__ == '__main__':
    unittest.main()
