import logging

CONTEXT_FIELDS = (
    'device',
    'device_info',
    'profiles',
    'changed_paths',
    'path',
    'key',
    'event',
    'command',
    'pid',
    'exit_status',
    'retry_seconds',
    'count',
    'limit',
    'layer',
    'mode',
    'error',
)


class ContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        context = ' '.join(
            f'{field_name}={getattr(record, field_name)!r}'
            for field_name in CONTEXT_FIELDS
            if getattr(record, field_name, None) is not None
        )
        return f'{message} {context}' if context else message


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ContextFormatter('%(levelname)s %(name)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
