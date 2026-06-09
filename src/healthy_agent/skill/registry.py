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

        for md_file in sorted(directory.glob("*.md")):
            if md_file.name.startswith("_"):
                continue
            try:
                skill = self._load_md_skill(md_file)
                if skill:
                    self.register(skill)
                    loaded += 1
            except Exception as e:
                logger.warning("Failed to load %s: %s", md_file.name, e)

        logger.info("Loaded %d skills from %s", loaded, directory)
        return loaded

    def _load_md_skill(self, path: Path) -> Skill | None:
        """Load a skill from a markdown file with YAML frontmatter."""
        import yaml

        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        meta = yaml.safe_load(parts[1])
        body = parts[2].strip()

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        params_def = meta.get("parameters", [])

        from .base import SkillParam, SkillResult

        params = [
            SkillParam(
                name=p["name"],
                type=p.get("type", "string"),
                description=p.get("description", ""),
                required=p.get("required", True),
            )
            for p in params_def
        ]

        system_prompt = ""
        user_template = body
        if "# System" in body and "# Prompt" in body:
            sys_part, prompt_part = body.split("# Prompt", 1)
            system_prompt = sys_part.replace("# System", "").strip()
            user_template = prompt_part.strip()

        class MdSkill(Skill):
            @property
            def name(self_inner): return name
            @property
            def description(self_inner): return description
            @property
            def parameters(self_inner): return params

            async def execute(self_inner, p, process=None, kernel=None):
                driver = p.get("_driver")
                if not driver:
                    return SkillResult(success=True, data=f"[mock] {name}: would process with LLM")
                try:
                    rendered = user_template
                    for param in params:
                        rendered = rendered.replace("{" + param.name + "}", str(p.get(param.name, "")))
                    sys_rendered = system_prompt
                    for param in params:
                        sys_rendered = sys_rendered.replace("{" + param.name + "}", str(p.get(param.name, "")))
                    result = await driver.generate(
                        [{"role": "user", "content": rendered}],
                        system=sys_rendered or "You are a helpful assistant.",
                    )
                    return SkillResult(success=result.success, data=result.data["text"].strip() if result.success else "", error=result.error)
                except Exception as e:
                    return SkillResult(success=False, error=str(e))

        return MdSkill()
