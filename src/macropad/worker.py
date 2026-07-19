import signal

from . import interceptor
from .actions import ActionExecutor
from .config import ProfileConfig
from .handlers import KeyboardHandler
from .logging_config import configure_logging


def install_shutdown_handler(shutdown_event) -> None:
    def request_shutdown(signum, frame):
        shutdown_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)


def run(
    profile_config: ProfileConfig,
    shutdown_event,
    action_debug: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    configure_logging(verbose=verbose, debug=debug or action_debug)
    install_shutdown_handler(shutdown_event)
    action_executor = ActionExecutor(device=profile_config.device, debug_output=action_debug)
    handler = KeyboardHandler(
        profile_config.keyboard,
        action_executor=action_executor,
        device=profile_config.device,
    )
    try:
        interceptor.listen(profile_config.device, handler, shutdown_event)
    finally:
        handler.shutdown()
