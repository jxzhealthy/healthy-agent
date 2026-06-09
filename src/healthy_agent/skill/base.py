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


class Tool(ABC):
    """Base capability — pure execution, no LLM needed.

    Tools are simple: input → execute → output.
    Examples: read_file, shell, http_request.
    """

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

    @property
    def requires_llm(self) -> bool:
        return False

    @abstractmethod
    async def execute(self, params: dict, process: Process | None = None, kernel: Kernel | None = None) -> SkillResult:
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


class Skill(Tool):
    """Extended Tool — can use LLM for intelligent processing.

    Skills inherit all Tool capabilities and add LLM access.
    The LLM driver is passed via params["_driver"].
    Examples: summarize, code_gen, translate.
    """

    @property
    def requires_llm(self) -> bool:
        return True
