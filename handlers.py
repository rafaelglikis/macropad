import os
import subprocess
import sys
from typing import Protocol

import evdev
from evdev import InputEvent, KeyEvent

from utils import debounce


class Handler(Protocol):
    """
    Protocol for Event handlers
    """

    def handle(self, e: InputEvent) -> None:
        """
        :param e:  Event to handle
        """

    @property
    def raw_data(self) -> dict:
        """
        :return: Raw data in dict format
        """


class KeyboardHandler:
    """
    Handles keyboard events
    """

    def __init__(self, config):
        self.bindings = config['bindings']
        self.dry_run = config['dry_run'] if 'dry_run' in config else False
        self.notifications = config['notifications'] if 'notifications' in config else False
        self.event_logs = []

    @property
    def raw_data(self) -> dict:
        raw_data = {
            "bindings": self.bindings,
        }

        if self.notifications:
            raw_data["notifications"] = self.notifications

        if self.dry_run:
            raw_data["dry_run"] = self.dry_run

        return raw_data

    def handle(self, e: InputEvent):
        event = evdev.categorize(e)
        print()
        if not isinstance(event, KeyEvent):
            return

        code = evdev.ecodes.KEY[e.code]
        if code not in self.bindings:
            print(f'No keybinding found for {event}')
            return

        self.event_logs.append(event)
        self.handle_event(event, code)

    @debounce(0.1)
    def handle_event(self, event: KeyEvent, code):
        print('---------------------------')
        current_key_bindings = self.bindings[code]
        event_value = self._map_event(event)

        if event_value not in current_key_bindings:
            print(f"No keybinding found for '{event_value}' on {event}")
            return

        print(f"Commands found for '{event_value}' on {event}")
        for command in current_key_bindings[event_value]:
            self.run_command(command)

    def _map_event(self, e: KeyEvent) -> str:
        previews_event = self.event_logs[-2]
        if previews_event.event.value == e.key_hold and previews_event.event.code == e.event.code:
            return 'hold'
        if self._is_double_tap(e):
            return 'double_tap'
        if e.event.value == e.key_up:
            return 'up'
        if e.event.value == e.key_down:
            return 'down'
        if e.event.value == e.key_hold:
            return 'hold'
        return ''

    def _is_double_tap(self, e: KeyEvent) -> bool:
        recent_event_logs = self.event_logs[-4:]
        self.event_logs = []
        if len(recent_event_logs) < 4:
            return False

        for i, recent_event in enumerate(recent_event_logs):
            if e.event.code != recent_event.event.code:
                return False
            expected_event = e.key_down if i % 2 == 0 else e.key_up
            if expected_event != recent_event.event.value:
                return False

        return True

    def run_command(self, command) -> int:
        print(f'Executing {command}')
        self.notify('Running command', command)
        if self.dry_run:
            return 0

        try:
            pid = os.fork()
            if pid > 0:
                os.waitid(os.P_PID, pid, os.WEXITED)

                return 1
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
        pipe = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = pipe.communicate()[0]

        os._exit(os.EX_OK)

        return 1

    def notify(self, title: str, message, *, expire_seconds: float = 3) -> None:
        if not self.notifications:
            return

        subprocess.call(['notify-send', title, message, '-t', str(expire_seconds * 1000)])
