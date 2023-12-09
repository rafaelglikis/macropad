from threading import Thread
from PIL import Image
import pystray


def create():
    icon = pystray.Icon('MacroPad', icon=create_image(1, 1, 'red'))
    thread = Thread(target=lambda: icon.run())
    thread.start()


def create_image(width, height, color):
    return Image.new('RGBA', (width, height), color)
