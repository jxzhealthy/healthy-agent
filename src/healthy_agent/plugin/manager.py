"""Plugin manager: loading, registration, and lifecycle management.

Supports:
  - Programmatic registration
  - Entry-point based discovery (pip install my-plugin)
  - Directory-based loading (drop .py files in plugins/)
"""
from __future__ import annotations

import importlib
import importlib.metadata
import logging
from pathlib import Path
from typing import Any

from .base import Plugin, PluginContext, PluginHook

logger = logging.getLogger("healthy_agent.plugin")

ENTRY_POINT_GROUP = "healthy_agent.plugins"


class PluginManager:
    """Manages plugin lifecycle and hook dispatch.

    Usage:
        pm = PluginManager()
        pm.register(MyPlugin())
        pm.load_directory("./plugins")
        pm.discover_entry_points()

        pm.start_all()
        pm.emit(PluginHook.ON_MESSAGE, session_id="abc", role="user", content="hi")
        pm.shutdown_all()
    """

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._load_order: list[str] = []

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance."""
        meta = plugin.metadata
        if meta.name in self._plugins:
            logger.warning("Plugin '%s' already registered, skipping", meta.name)
            return

        # Check dependencies
        for dep in meta.requires:
            if dep not in self._plugins:
                raise RuntimeError(
                    f"Plugin '{meta.name}' requires '{dep}' which is not registered"
                )

        ctx = PluginContext()
        plugin.on_register(ctx)

        self._plugins[meta.name] = plugin
        self._contexts[meta.name] = ctx
        self._load_order.append(meta.name)
        logger.info("Plugin registered: %s v%s", meta.name, meta.version)

    def unregister(self, name: str) -> None:
        """Remove a plugin."""
        if name in self._plugins:
            plugin = self._plugins.pop(name)
            self._contexts.pop(name, None)
            self._load_order.remove(name)
            plugin.on_shutdown()
            logger.info("Plugin unregistered: %s", name)

    def load_directory(self, directory: str | Path) -> int:
        """Load all .py plugin files from a directory.

        Each file must define a `plugin` variable that is a Plugin instance,
        or a `create_plugin()` function that returns one.
        """
        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            return 0

        loaded = 0
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_plugin_{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    plugin = getattr(module, "plugin", None)
                    if plugin is None:
                        factory = getattr(module, "create_plugin", None)
                        if factory:
                            plugin = factory()

                    if isinstance(plugin, Plugin):
                        self.register(plugin)
                        loaded += 1
                    else:
                        logger.warning("No Plugin found in %s", py_file.name)
            except Exception as exc:
                logger.error("Failed to load plugin %s: %s", py_file.name, exc)

        return loaded

    def discover_entry_points(self) -> int:
        """Discover plugins via setuptools entry points."""
        loaded = 0
        try:
            eps = importlib.metadata.entry_points()
            group = eps.get(ENTRY_POINT_GROUP, []) if isinstance(eps, dict) else eps.select(group=ENTRY_POINT_GROUP)
            for ep in group:
                try:
                    plugin_or_factory = ep.load()
                    if isinstance(plugin_or_factory, Plugin):
                        self.register(plugin_or_factory)
                    elif callable(plugin_or_factory):
                        self.register(plugin_or_factory())
                    loaded += 1
                except Exception as exc:
                    logger.error("Failed to load entry point '%s': %s", ep.name, exc)
        except Exception as exc:
            logger.debug("Entry point discovery failed: %s", exc)
        return loaded

    def start_all(self) -> None:
        """Call on_start for all registered plugins."""
        for name in self._load_order:
            try:
                self._plugins[name].on_start()
            except Exception as exc:
                logger.error("Plugin '%s' on_start failed: %s", name, exc)

    def shutdown_all(self) -> None:
        """Call on_shutdown for all registered plugins (reverse order)."""
        for name in reversed(self._load_order):
            try:
                self._plugins[name].on_shutdown()
            except Exception as exc:
                logger.error("Plugin '%s' on_shutdown failed: %s", name, exc)

    def emit(self, hook: PluginHook, **kwargs) -> None:
        """Dispatch a lifecycle event to all plugins."""
        method_name = hook.value
        for name in self._load_order:
            plugin = self._plugins[name]
            handler = getattr(plugin, method_name, None)
            if handler:
                try:
                    handler(**kwargs)
                except Exception as exc:
                    logger.error("Plugin '%s' hook '%s' failed: %s", name, method_name, exc)

    def pre_generate(self, messages: list[dict], **kwargs) -> list[dict]:
        """Run pre_generate through all plugins (pipeline)."""
        for name in self._load_order:
            messages = self._plugins[name].pre_generate(messages, **kwargs)
        return messages

    def post_generate(self, result: Any) -> Any:
        """Run post_generate through all plugins (pipeline)."""
        for name in self._load_order:
            result = self._plugins[name].post_generate(result)
        return result

    @property
    def all_skills(self) -> list[Any]:
        """Collect all skills registered by plugins."""
        skills = []
        for ctx in self._contexts.values():
            skills.extend(ctx.skills)
        return skills

    @property
    def all_drivers(self) -> dict[str, Any]:
        """Collect all custom drivers registered by plugins."""
        drivers = {}
        for ctx in self._contexts.values():
            drivers.update(ctx.drivers)
        return drivers

    def list_plugins(self) -> list[dict]:
        """List all registered plugins."""
        return [
            {
                "name": p.metadata.name,
                "version": p.metadata.version,
                "description": p.metadata.description,
                "skills": len(self._contexts[p.metadata.name].skills),
            }
            for p in self._plugins.values()
        ]

    @property
    def count(self) -> int:
        return len(self._plugins)
