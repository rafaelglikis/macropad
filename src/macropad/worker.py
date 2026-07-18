import signal

from . import interceptor
from .config import ProfileConfig
from .handlers import KeyboardHandler


def install_shutdown_handler(shutdown_event) -> None:
    def request_shutdown(signum, frame):
        shutdown_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)


def run(profile_config: ProfileConfig, shutdown_event) -> None:
    install_shutdown_handler(shutdown_event)
    handler = KeyboardHandler(profile_config.keyboard, device=profile_config.device)
    try:
        interceptor.listen(profile_config.device, handler, shutdown_event)
    finally:
        handler.shutdown()
