import logging
from importlib.resources import files

import notify2

DEFAULT_ICON = files('macropad').joinpath('assets/macropad.svg')
logger = logging.getLogger(__name__)


def check_availability() -> str | None:
    try:
        initialized = notify2.init('Macropad')
    except Exception as error:
        return str(error)
    if initialized is False:
        return 'notification backend did not initialize'
    return None


def initialize() -> None:
    error = check_availability()
    if error is not None:
        logger.warning(
            'notification initialization failed; continuing without notifications',
            extra={'error': error},
        )


def send(title: str, message: str, icon_path: str | None = None) -> None:
    try:
        notification = notify2.Notification(
            summary=title,
            message=message,
            icon=str(icon_path or DEFAULT_ICON),
        )
        notification.show()
    except Exception as error:
        logger.warning('notification failed', extra={'error': str(error)})
