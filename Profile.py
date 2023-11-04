import yaml

from event_handlers.DebugHandler import DebugHandler
from event_handlers.EchoHandler import EchoHandler
from event_handlers.VoidHandler import VoidHandler


def create_handler_from_config(handler):
    if handler['name'] == 'debug':
        return DebugHandler()
    if handler['name'] == 'echo':
        return EchoHandler()
    print(f"Handler named {handler['name']} not found!")
    return VoidHandler()


class Profile:
    def __init__(self, filename: str = 'profile.yml'):
        with open(filename, 'r') as file:
            profile = yaml.safe_load(file)
            self.device = profile['device']
            self.version = profile['version']
            self.handlers = []
            for handler in profile['handlers']:
                handler = create_handler_from_config(handler)
                print(f'Loaded handler {handler}')
                self.handlers.append(handler)
