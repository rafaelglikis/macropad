import evdev
from evdev import InputEvent


class EchoHandler:
    def __init__(self):
        self.input = evdev.uinput.UInput()

    def handle(self, e: InputEvent):
        self.input.write(e.type, e.code, e.value)
        self.input.syn()
