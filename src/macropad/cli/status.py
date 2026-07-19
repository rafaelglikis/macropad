from .. import runtime_status
from . import service


def _format_retry(retry_seconds) -> str:
    if retry_seconds is None:
        return ''
    return f' (retry in {retry_seconds:.1f}s)'


def run() -> int:
    try:
        status = runtime_status.request_status()
    except runtime_status.RuntimeStatusUnavailable as error:
        service_info = service.get_info()
        print(f'Runtime status unavailable: {error}')
        if service_info.active:
            print('The systemd service is active; inspect it with: macropad service status')
        else:
            print('Macropad is not running. Start it with: macropad listen')
        return 1

    print(f'Macropad parent PID: {status.get("pid", "unknown")}')
    configuration_error = status.get('configuration_error')
    if configuration_error:
        print(f'Configuration: INVALID candidate retained ({configuration_error})')

    workers = status.get('workers', [])
    if not workers:
        print('No configured keyboard workers.')
        return 0

    for worker in workers:
        print()
        print(worker['device'])
        retry = _format_retry(worker.get('retry_seconds'))
        print(f'  state: {worker["state"]}{retry}')
        if worker.get('pid') is not None:
            print(f'  pid: {worker["pid"]}')
        print(f'  profiles: {", ".join(worker["profiles"])}')
        paths = worker.get('paths', [])
        if paths:
            print(f'  paths: {", ".join(paths)}')
        if worker.get('error'):
            print(f'  error: {worker["error"]}')
    return 0
