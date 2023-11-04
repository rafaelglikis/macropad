import evdev
from evdev import InputEvent


class DebugHandler:
    def handle(self, e: InputEvent):
        print('Raw event: ', e)
        print('Keyboard event: ', evdev.categorize(e))
