import logging
from importlib.resources import files

import notify2

DEFAULT_ICON = files('macropad').joinpath('assets/macropad.svg')
logger = logging.getLogger(__name__)


def initialize() -> None:
    try:
        notify2.init('Macropad')
    except Exception as error:
        logger.warning(
            'notification initialization failed; continuing without notifications',
            extra={'error': str(error)},
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
