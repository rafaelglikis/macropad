import signal

from . import interceptor, notifications
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
    status_queue=None,
    worker_id: int = 0,
    notifications_enabled: bool = True,
) -> None:
    configure_logging(verbose=verbose, debug=debug or action_debug)
    notifications.configure(notifications_enabled)
    install_shutdown_handler(shutdown_event)
    last_status = None

    def report_status(state: str, paths=(), error: str | None = None) -> None:
        nonlocal last_status
        status = (state, tuple(paths), error)
        if status_queue is None or status == last_status:
            return
        last_status = status
        try:
            status_queue.put(
                {
                    'worker_id': worker_id,
                    'device': profile_config.device,
                    'state': state,
                    'paths': tuple(paths),
                    'error': error,
                }
            )
        except (OSError, ValueError):
            pass

    action_executor = ActionExecutor(device=profile_config.device, debug_output=action_debug)
    handler = KeyboardHandler(
        profile_config.keyboard,
        action_executor=action_executor,
        device=profile_config.device,
    )
    report_status('waiting')
    try:
        if status_queue is None:
            interceptor.listen(profile_config.device, handler, shutdown_event)
        else:
            interceptor.listen(
                profile_config.device,
                handler,
                shutdown_event,
                status_callback=report_status,
            )
    except Exception as error:
        error_paths = ()
        if last_status is not None and last_status[0] == 'error':
            error_paths = last_status[1]
        report_status('error', error_paths, str(error))
        raise
    finally:
        if shutdown_event.is_set():
            report_status('shutting_down')
        handler.shutdown()
