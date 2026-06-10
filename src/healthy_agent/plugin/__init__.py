"""Plugin system: standardized interface for third-party extensions."""
from .base import Plugin, PluginMetadata, PluginHook
from .manager import PluginManager

__all__ = ["Plugin", "PluginMetadata", "PluginHook", "PluginManager"]
