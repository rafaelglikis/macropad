import logging
import pathlib
from importlib.resources import files

import notify2


DEFAULT_ICON = files('macropad').joinpath('assets/macropad.svg')
DEFAULT_CONFIG_DIR = pathlib.Path.home() / ".config" / "macropad" / "profiles"
logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, icon_path: str = None):
    """Send a desktop notification, gracefully handling errors."""
    try:
        notification = notify2.Notification(
            summary=title,
            message=message,
            icon=str(icon_path or DEFAULT_ICON),
        )
        notification.show()
    except Exception as e:
        logger.warning('notification failed', extra={'error': str(e)})
