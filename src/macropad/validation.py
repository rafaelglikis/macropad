import sys
from collections.abc import Sequence
from typing import TextIO

from . import profiles
from .config import ProfileValidationError


def run(
    profile_paths: Sequence[str],
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    loaded_profiles = []
    validation_errors = {}
    for profile_path in profile_paths:
        try:
            profile_config = profiles.load_yml(profile_path)
        except Exception as error:
            validation_errors[profile_path] = error
            continue
        loaded_profiles.append((profile_path, profile_config))

    prepared_profiles = None
    profile_set_error = None
    if not validation_errors:
        try:
            prepared_profiles = profiles.prepare_loaded_profiles(loaded_profiles)
        except Exception as error:
            if isinstance(error, ProfileValidationError) and error.source in profile_paths:
                validation_errors[error.source] = error
            else:
                profile_set_error = error

    failed = bool(validation_errors or profile_set_error)
    output = stderr if failed else stdout
    for index, profile_path in enumerate(profile_paths):
        if index:
            print(file=output)
        print(profile_path, file=output)
        error = validation_errors.get(profile_path)
        if error is None:
            status = 'PARSED' if failed else 'PASS'
            print(f'  {status}', file=output)
            continue

        print('  FAIL', file=output)
        if isinstance(error, ProfileValidationError):
            details = f'{error.path}: {error.message}' if error.path else error.message
        else:
            details = str(error)
        for line in details.splitlines():
            print(f'  {line}', file=output)

    if profile_set_error is not None:
        print(file=output)
        print('Profile set', file=output)
        print('  FAIL', file=output)
        for line in str(profile_set_error).splitlines():
            print(f'  {line}', file=output)

    print(file=output)
    if failed:
        if profile_set_error is not None:
            print('Validation failed: profile set could not be merged.', file=output)
        else:
            profile_file_label = 'profile file' if len(profile_paths) == 1 else 'profile files'
            error_verb = 'has' if len(validation_errors) == 1 else 'have'
            print(
                f'Validation failed: {len(validation_errors)} of '
                f'{len(profile_paths)} {profile_file_label} {error_verb} errors.',
                file=output,
            )
        print(
            'Files marked PARSED passed standalone validation; merged validation did not complete.',
            file=output,
        )
        return 1

    assert prepared_profiles is not None
    profile_file_label = 'profile file' if len(profile_paths) == 1 else 'profile files'
    device_label = 'device' if len(prepared_profiles) == 1 else 'devices'
    print(
        f'Validated {len(profile_paths)} {profile_file_label} '
        f'for {len(prepared_profiles)} {device_label}.',
        file=output,
    )
    return 0
