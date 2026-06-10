"""Plugin base classes and interfaces.

A plugin can:
  - Register new skills (tools)
  - Add middleware to the execution pipeline
  - Provide custom drivers
  - Hook into lifecycle events (on_start, on_message, on_complete, etc.)

Example:
    class MyPlugin(Plugin):
        metadata = PluginMetadata(name="my-plugin", version="1.0.0")

        def on_register(self, ctx):
            ctx.add_skill(MyCustomSkill())

        def on_message(self, session_id, role, content):
            print(f"[{session_id}] {role}: {content[:50]}")
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PluginHook(str, Enum):
    """Lifecycle hooks a plugin can subscribe to."""
    ON_REGISTER = "on_register"
    ON_START = "on_start"
    ON_SHUTDOWN = "on_shutdown"
    ON_MESSAGE = "on_message"
    ON_TASK_START = "on_task_start"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_ERROR = "on_error"
    PRE_GENERATE = "pre_generate"
    POST_GENERATE = "post_generate"


@dataclass
class PluginMetadata:
    """Plugin metadata for discovery and dependency management."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    requires: list[str] = field(default_factory=list)  # Other plugin names
    tags: list[str] = field(default_factory=list)


class PluginContext:
    """Context passed to plugins during registration.

    Provides access to register skills, drivers, and middleware.
    """

    def __init__(self):
        self._skills: list[Any] = []
        self._drivers: dict[str, Any] = {}
        self._middleware: list[Any] = []
        self._config: dict[str, Any] = {}

    def add_skill(self, skill: Any) -> None:
        """Register a new skill from the plugin."""
        self._skills.append(skill)

    def add_driver(self, name: str, driver: Any) -> None:
        """Register a custom LLM driver."""
        self._drivers[name] = driver

    def add_middleware(self, middleware: Any) -> None:
        """Add execution middleware."""
        self._middleware.append(middleware)

    def set_config(self, key: str, value: Any) -> None:
        """Set a plugin-specific config value."""
        self._config[key] = value

    @property
    def skills(self) -> list[Any]:
        return self._skills

    @property
    def drivers(self) -> dict[str, Any]:
        return self._drivers

    @property
    def middleware(self) -> list[Any]:
        return self._middleware


class Plugin(ABC):
    """Base class for all plugins.

    Subclass this and implement the hooks you need.
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        ...

    def on_register(self, ctx: PluginContext) -> None:
        """Called when plugin is registered. Use ctx to add skills/drivers."""
        pass

    def on_start(self) -> None:
        """Called when the application starts."""
        pass

    def on_shutdown(self) -> None:
        """Called when the application shuts down."""
        pass

    def on_message(self, session_id: str, role: str, content: str) -> None:
        """Called when a message is added to a session."""
        pass

    def on_task_start(self, task_type: str, payload: dict) -> None:
        """Called when a task begins execution."""
        pass

    def on_task_complete(self, task_type: str, result: Any) -> None:
        """Called when a task completes."""
        pass

    def on_error(self, error: Exception, context: dict) -> None:
        """Called when an error occurs."""
        pass

    def pre_generate(self, messages: list[dict], **kwargs) -> list[dict]:
        """Modify messages before LLM generation. Return modified messages."""
        return messages

    def post_generate(self, result: Any) -> Any:
        """Modify generation result. Return modified result."""
        return result
