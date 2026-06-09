from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel
    from ..kernel.process import Process


@dataclass
class SkillParam:
    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class SkillResult:
    success: bool
    data: Any = None
    error: str = ""


class Skill(ABC):
    """A loadable kernel module — encapsulates reusable agent capability."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    def parameters(self) -> list[SkillParam]:
        return []

    @abstractmethod
    async def execute(self, params: dict, process: Process, kernel: Kernel) -> SkillResult:
        ...

    def to_schema(self) -> dict:
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": props, "required": required},
        }
