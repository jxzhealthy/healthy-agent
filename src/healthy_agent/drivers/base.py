from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class IOResult:
    success: bool
    data: Any = None
    error: str = ""
    tokens_used: int = 0


class Driver(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def driver_type(self) -> str:
        ...


class LLMDriver(Driver):
    @property
    def driver_type(self) -> str:
        return "llm"

    @abstractmethod
    async def generate(self, messages: list[dict], **kwargs) -> IOResult:
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], **kwargs):
        ...


class ToolDriver(Driver):
    @property
    def driver_type(self) -> str:
        return "tool"

    @abstractmethod
    async def invoke(self, action: str, params: dict) -> IOResult:
        ...

    @abstractmethod
    def capabilities(self) -> list[str]:
        ...
