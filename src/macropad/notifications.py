import importlib
import logging
from importlib.resources import files

DEFAULT_ICON = files('macropad').joinpath('assets/macropad.svg')
logger = logging.getLogger(__name__)
_enabled = True
_backend = None
_unavailable_error = None


def configure(enabled: bool = True) -> None:
    global _backend, _enabled, _unavailable_error
    _enabled = enabled
    _backend = None
    _unavailable_error = None


def _error_message(error: Exception) -> str:
    if isinstance(error, ModuleNotFoundError):
        return (
            'notification dependencies are not installed; install poor-mans-macropad[notifications]'
        )
    return str(error)


def _get_backend(log_failure: bool):
    global _backend, _unavailable_error
    if not _enabled or _unavailable_error is not None:
        return None
    if _backend is not None:
        return _backend

    try:
        backend = importlib.import_module('notify2')
        initialized = backend.init('Macropad')
        if initialized is False:
            raise RuntimeError('notification backend did not initialize')
    except Exception as error:
        _unavailable_error = _error_message(error)
        if log_failure:
            logger.warning(
                'notification initialization failed; continuing without notifications',
                extra={'error': _unavailable_error},
            )
        return None

    _backend = backend
    return _backend


def check_availability() -> str | None:
    if not _enabled:
        return 'disabled by --no-notifications'
    _get_backend(log_failure=False)
    return _unavailable_error


def send(title: str, message: str, icon_path: str | None = None) -> None:
    global _backend, _unavailable_error
    backend = _get_backend(log_failure=True)
    if backend is None:
        return
    try:
        notification = backend.Notification(
            summary=title,
            message=message,
            icon=str(icon_path or DEFAULT_ICON),
        )
        notification.show()
    except Exception as error:
        _unavailable_error = str(error)
        _backend = None
        logger.warning(
            'notification failed; continuing without notifications',
            extra={'error': _unavailable_error},
        )
