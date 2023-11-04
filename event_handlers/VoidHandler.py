from evdev import InputEvent


class VoidHandler:
    def handle(self, e: InputEvent):
        pass
