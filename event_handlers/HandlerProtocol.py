from typing import Protocol

from evdev import InputEvent


class EatsBread(Protocol):
    def handle(self, event: InputEvent):
        pass
