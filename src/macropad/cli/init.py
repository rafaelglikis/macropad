import argparse
import io
import math
import re
from pathlib import Path

import yaml

from .. import diagnostics, interceptor, profiles, validation
from . import profile_files, service

UP_EVENT = 'up'


def timeout_seconds(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('timeout must be a number') from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError('timeout must be a finite number greater than zero')
    return timeout


def _render_input_checks(results: list[diagnostics.DiagnosticResult]) -> None:
    for result in results:
        print(f'{result.status} {result.name}: {result.message}')
        if result.remediation:
            label = 'Fix' if result.blocking else 'Note'
            print(f'  {label}: {result.remediation}')


def _load_profile_set(profile_directory: Path):
    profile_paths = sorted(profile_directory.glob('*.yml')) if profile_directory.exists() else []
    loaded_profiles = [(str(path), profiles.load_yml(str(path))) for path in profile_paths]
    prepared_profiles = profiles.prepare_loaded_profiles(loaded_profiles)
    return profile_paths, loaded_profiles, prepared_profiles


def _profile_for_device(prepared_profiles, device_name: str):
    return next(
        (profile for profile in prepared_profiles if profile.device_name == device_name),
        None,
    )


def _event_is_bound(prepared_profile, key_name: str) -> bool:
    if prepared_profile is None:
        return False
    binding = prepared_profile.config.keyboard.bindings.get(key_name)
    return binding is not None and UP_EVENT in binding.actions


def _confirm_new_fragment() -> bool:
    while True:
        answer = input('Create a new profile fragment for this device? [Y/n] ').strip().lower()
        if answer in ('', 'y', 'yes'):
            return True
        if answer in ('n', 'no', 'cancel'):
            return False
        print('Enter y to continue or n to cancel.')


def _prompt_for_command() -> str:
    while True:
        command = input('Command to run when the key is released: ').strip()
        if command:
            return command
        print('The command cannot be empty. Press Ctrl+C to cancel.')


def _slug(value: str, fallback: str) -> str:
    slug = '_'.join(re.findall(r'[a-z0-9]+', value.lower()))
    return slug[:60].rstrip('_') or fallback


def _candidate_path(profile_directory: Path, device_name: str, key_name: str) -> Path:
    stem = f'{_slug(device_name, "macropad")}_{_slug(key_name, "key")}'
    candidate = profile_directory / f'{stem}.yml'
    suffix = 2
    while candidate.exists():
        candidate = profile_directory / f'{stem}_{suffix}.yml'
        suffix += 1
    return candidate


def _profile_data(device_name: str, key_name: str, command: str) -> dict:
    return {
        'device': device_name,
        'version': '1',
        'bindings': {key_name: command},
    }


def _write_validated_profile(
    profile_directory: Path,
    device_name: str,
    key_name: str,
    command: str,
) -> Path:
    profile_directory.mkdir(parents=True, exist_ok=True)

    while True:
        _, loaded_profiles, _ = _load_profile_set(profile_directory)
        candidate_path = _candidate_path(profile_directory, device_name, key_name)
        profile_data = _profile_data(device_name, key_name, command)
        candidate_config = profiles.validate_profile_data(profile_data, source=str(candidate_path))
        profiles.prepare_loaded_profiles(
            [*loaded_profiles, (str(candidate_path), candidate_config)]
        )

        try:
            with candidate_path.open('x', encoding='utf-8') as profile_file:
                yaml.safe_dump(profile_data, profile_file, sort_keys=False)
        except FileExistsError:
            continue
        except BaseException:
            candidate_path.unlink(missing_ok=True)
            raise

        try:
            validation_output = io.StringIO()
            current_paths = [str(path) for path in sorted(profile_directory.glob('*.yml'))]
            if validation.run(
                current_paths,
                stdout=validation_output,
                stderr=validation_output,
            ):
                details = validation_output.getvalue().strip()
                raise ValueError(f'generated profile failed validation:\n{details}')
        except BaseException:
            candidate_path.unlink(missing_ok=True)
            raise
        return candidate_path


def _print_next_step(profile_path: Path, service_info: service.ServiceInfo) -> None:
    print(f'Created and validated {profile_path}')
    if service_info.active:
        print('The systemd service is active, but active state alone cannot confirm watch mode.')
        print(
            'It will load this fragment if it uses the standard listen --watch command for the '
            'default profile directory.'
        )
        print('Next command: macropad service status')
        return

    print('The systemd service is not active, so it is not watching for this profile yet.')
    print('Next foreground command: macropad listen')
    if service_info.fragment_path:
        print('Or start the installed service: macropad service start')


def run(args: argparse.Namespace) -> int:
    written_path = None
    try:
        service_info = service.get_info()
        print('Checking input-device access...')
        input_results = diagnostics.check_input_devices(service_info.active)
        _render_input_checks(input_results)
        if any(result.blocking for result in input_results):
            print('Initialization stopped because input access is not ready.')
            return 1

        if service_info.active:
            print(
                'Note: the Macropad service is active. If it already owns this keyboard, stop the '
                'service before retrying initialization.'
            )

        print()
        print('Disconnect the keyboard you want to configure.')
        print('Detection only considers devices connected after the next step starts.')
        input('Press Enter when the keyboard is disconnected and you are ready. ')
        print(
            f'Reconnect the keyboard and press one macro key within {args.timeout:g} seconds.',
            flush=True,
        )
        detected = interceptor.detect(args.timeout)
        print(
            f'Detected {detected.device_name!r} on {detected.path}; captured {detected.key_name}.'
        )

        profile_directory = profile_files.DEFAULT_CONFIG_DIR
        _, _, prepared_profiles = _load_profile_set(profile_directory)
        prepared_profile = _profile_for_device(prepared_profiles, detected.device_name)
        if prepared_profile is not None:
            print('Existing profile fragments for this device:')
            for path in prepared_profile.paths:
                print(f'  {path}')
            if not _confirm_new_fragment():
                print('Initialization canceled. No profile was written.')
                return 130

        while _event_is_bound(prepared_profile, detected.key_name):
            print(f'{detected.key_name} already has a release binding for this device.')
            answer = input('Press Enter to capture another key, or type cancel to stop: ').strip()
            if answer.lower() == 'cancel':
                print('Initialization canceled. No profile was written.')
                return 130
            print(
                f'Release all keys, then press another key within {args.timeout:g} seconds.',
                flush=True,
            )
            detected = interceptor.capture_key(detected.device_name, args.timeout)
            print(f'Captured {detected.key_name}.')

        print('Profile commands are trusted shell code and will run with your user permissions.')
        command = _prompt_for_command()
        written_path = _write_validated_profile(
            profile_directory,
            detected.device_name,
            detected.key_name,
            command,
        )
        _print_next_step(written_path, service.get_info())
        return 0
    except (KeyboardInterrupt, EOFError):
        if written_path is not None:
            written_path.unlink(missing_ok=True)
        print('\nInitialization canceled. No partial profile was left behind.')
        return 130
    except TimeoutError as error:
        if written_path is not None:
            written_path.unlink(missing_ok=True)
        print(f'Initialization timed out: {error}')
        print('No profile was written. Run macropad init to try again.')
        return 1
    except Exception as error:
        if written_path is not None:
            written_path.unlink(missing_ok=True)
        print(f'Initialization failed: {error}')
        print('No partial profile was left behind.')
        return 1
