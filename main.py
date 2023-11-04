import yaml

from event_handlers.DebugHandler import DebugHandler
from event_handlers.EchoHandler import EchoHandler
from interceptor import listen


def main():
    try:
        # with open('profile.yml', 'r') as file:
        #     profile = yaml.safe_load(file)
        #     print(profile)
        listen('Generic USB Keyboard', [
            EchoHandler(),
            DebugHandler(),
        ])
    except KeyboardInterrupt:
        print('Keyboard interrupt exiting')
        return


if __name__ == '__main__':
    main()
