"""Turn every keyboard into a macropad."""

from importlib.metadata import PackageNotFoundError, version

PROFILE_DOCS_URL = 'https://github.com/rafaelglikis/macropad/blob/main/docs/profiles.md'

try:
    __version__ = version('poor-mans-macropad')
except PackageNotFoundError:
    __version__ = '0.0.0+unknown'
