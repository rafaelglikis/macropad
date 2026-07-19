"""Turn every keyboard into a macropad."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('poor-mans-macropad')
except PackageNotFoundError:
    __version__ = '0.0.0+unknown'
