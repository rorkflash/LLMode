"""Configuration package: filesystem paths and layered settings.

Import the singletons from here:
    from llmode.config import get_settings, paths
"""

from llmode.config import paths
from llmode.config.settings import Settings, get_settings

__all__ = ["paths", "Settings", "get_settings"]
