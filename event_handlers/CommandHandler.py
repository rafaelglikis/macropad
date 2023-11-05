import os
import subprocess
import sys

import evdev
from evdev import InputEvent, KeyEvent


def _map_event(e: KeyEvent) -> str:
    if e.event.value == e.key_up:
        return 'up'
    if e.event.value == e.key_down:
        return 'down'
    if e.event.value == e.key_hold:
        return 'hold'
    return ''


class CommandHandler:
    def __init__(self, config):
        self.binds = config['binds']
        self.dry_run = config['dry_run'] if 'dry_run' in config else False

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        code = evdev.ecodes.KEY[e.code]
        if code not in self.binds:
            print(f'No keybinding found for {event}')
            return

        current_key_bindings = self.binds[code]
        event_value = _map_event(event)

        if event_value not in current_key_bindings:
            print(f"No keybinding found for '{event_value}' on {event}")
            return

        print(f"Commands found for '{event_value}' on {event}")
        for command in current_key_bindings[event_value]:
            self.run_command(command)

    def run_command(self, command) -> None:
        print(f'Executing {command}')
        if self.dry_run:
            return

        try:
            pid = os.fork()
            if pid > 0:
                os.waitid(os.P_PID, pid, os.WEXITED)
        except Exception as e:
            print(e)
            sys.exit(1)

        os.setsid()

        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except Exception as e:
            print(e)

            sys.exit(1)

        subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        os._exit(os.EX_OK)
