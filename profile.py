import yaml
from dataclasses import dataclass

from handlers import Handler, KeyboardHandler


@dataclass
class Profile:
    device: str
    version: str
    handler: Handler


def create_from_yml(filename: str) -> Profile:
    with open(filename, 'r') as file:
        profile = yaml.safe_load(file)
        return Profile(profile['device'], profile['version'], KeyboardHandler(profile))
