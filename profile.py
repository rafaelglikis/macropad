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
    with open(filename, 'r') as file:
        profile = yaml.safe_load(file)
        return Profile(profile['device'], profile['version'], KeyboardHandler(profile))


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
