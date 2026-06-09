from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .base import Tool, Skill, SkillResult

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel
    from ..kernel.process import Process

logger = logging.getLogger("healthy_agent.skill")


class SkillRegistry:
    """Manages loadable skills — supports auto-discovery from directory."""

    def __init__(self):
        self._skills: dict[str, Tool] = {}

    def register(self, skill: Tool) -> None:
        self._skills[skill.name] = skill
        logger.debug("Registered: %s (%s)", skill.name, "skill" if skill.requires_llm else "tool")

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [s.to_schema() for s in self._skills.values()]

    async def invoke(self, name: str, params: dict, process: Process | None, kernel: Kernel | None) -> SkillResult:
        skill = self.get(name)
        if not skill:
            return SkillResult(success=False, error=f"Skill not found: {name}")
        try:
            return await skill.execute(params, process, kernel)
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    @property
    def count(self) -> int:
        return len(self._skills)

    def load_directory(self, directory: str | Path) -> int:
        """Auto-discover and register all Tool/Skill classes from .py files in a directory.

        Each .py file is imported as a module. All classes that inherit Tool or Skill
        (and are not abstract) are instantiated and registered.

        Returns the number of skills loaded.
        """
        directory = Path(directory)
        if not directory.exists():
            logger.warning("Skills directory not found: %s", directory)
            return 0

        loaded = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                module_name = f"skills_plugin.{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, Tool) and obj not in (Tool, Skill) and not inspect.isabstract(obj)):
                        try:
                            instance = obj()
                            self.register(instance)
                            loaded += 1
                        except Exception as e:
                            logger.warning("Failed to instantiate %s: %s", obj.__name__, e)
            except Exception as e:
                logger.warning("Failed to load %s: %s", py_file.name, e)

        logger.info("Loaded %d skills from %s", loaded, directory)
        return loaded
