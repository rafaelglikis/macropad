from .. import diagnostics
from . import profile_files, service


def run() -> int:
    service_info = service.get_info()
    results = diagnostics.run_checks(
        profile_files.DEFAULT_CONFIG_DIR,
        service_info.fragment_path,
        service_info.active,
        service_info.error,
        service_info.action_path,
    )
    for result in results:
        print(f'{result.status} {result.name}: {result.message}')
        if result.remediation:
            label = 'Fix' if result.blocking else 'Note'
            print(f'  {label}: {result.remediation}')

    failure_count = sum(result.blocking for result in results)
    print()
    if failure_count:
        print(f'Doctor found {failure_count} blocking issue(s).')
        return 1
    print('Doctor found no blocking issues.')
    return 0
