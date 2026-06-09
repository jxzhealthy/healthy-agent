from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Skill, SkillResult

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel
    from ..kernel.process import Process


class SkillRegistry:
    """Manages loadable skills — like a kernel module registry."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [s.to_schema() for s in self._skills.values()]

    async def invoke(self, name: str, params: dict, process: Process, kernel: Kernel) -> SkillResult:
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
