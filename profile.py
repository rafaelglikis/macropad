import yaml
from dataclasses import dataclass

from handlers import Handler, KeyboardHandler


@dataclass
class Profile:
    device: str
    version: str
    handler: Handler

    @property
    def raw_data(self) -> dict:
        data = {
            "device": self.device,
            "version": self.version,
        }

        return data | self.handler.raw_data

    def dump(self) -> str:
        return yaml.dump(self.raw_data, sort_keys=False)

    def __getstate__(self):
        return self.__dict__.copy()

    def __setstate__(self, state):
        self.__dict__.update(state)


def create_from_yml(filename: str) -> Profile:
    return create_from_data(load_yml(filename))


def load_yml(filename: str) -> dict:
    with open(filename, 'r') as file:
        return yaml.safe_load(file)


def create_from_data(profile_data: dict) -> Profile:
    return Profile(profile_data['device'], profile_data.get('version', 1), KeyboardHandler(profile_data))


def merge_data(profile_datas: list[dict]) -> dict:
    if not profile_datas:
        raise ValueError("No profile data to merge")

    device = profile_datas[0]['device']
    merged = {
        'device': device,
        'version': profile_datas[0].get('version', 1),
        'bindings': {},
        'layers': {},
    }

    for profile_data in profile_datas:
        if profile_data['device'] != device:
            raise ValueError("Cannot merge profiles for different devices")

        merged['notifications'] = merged.get('notifications', False) or profile_data.get('notifications', False)
        merged['dry_run'] = merged.get('dry_run', False) or profile_data.get('dry_run', False)
        _merge_mapping(merged['bindings'], profile_data.get('bindings', {}), 'bindings')
        _merge_mapping(merged['layers'], profile_data.get('layers', {}), 'layers')

    return merged


def _merge_mapping(target: dict, source: dict, context: str) -> None:
    for key, value in source.items():
        if key not in target:
            target[key] = value
            continue

        if isinstance(target[key], dict) and isinstance(value, dict):
            _merge_mapping(target[key], value, f"{context}.{key}")
            continue

        if target[key] == value:
            continue

        raise ValueError(f"Duplicate conflicting profile entry: {context}.{key}")


def create_sample(device):
    return Profile(
        device=device.name,
        version='1',
        handler=KeyboardHandler({
            "device": device.name,
            "bindings": {
                "KEY_UP": {
                    "up": [
                        "notify-send Hey! 'Hello from macropad!'"
                    ],
                }
            }
        })
    )
