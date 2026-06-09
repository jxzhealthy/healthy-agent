from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Skill, SkillParam, SkillResult

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel
    from ..kernel.process import Process


class SummarizeSkill(Skill):
    """Summarizes text using an LLM driver."""

    @property
    def name(self) -> str:
        return "summarize"

    @property
    def description(self) -> str:
        return "Summarize a piece of text into a concise summary."

    @property
    def parameters(self) -> list[SkillParam]:
        return [
            SkillParam(name="text", type="string", description="Text to summarize"),
            SkillParam(name="max_sentences", type="integer", description="Max sentences", required=False),
        ]

    async def execute(self, params: dict, process: Process, kernel: Kernel) -> SkillResult:
        text = params.get("text", "")
        max_s = params.get("max_sentences", 3)
        if not text:
            return SkillResult(success=False, error="Missing 'text'")

        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would summarize {len(text)} chars into {max_s} sentences")

        result = await driver.generate(
            [{"role": "user", "content": f"Summarize in {max_s} sentences:\n\n{text}"}],
            system=f"Write exactly {max_s} sentences.",
        )
        if result.success:
            return SkillResult(success=True, data=result.data["text"].strip())
        return SkillResult(success=False, error=result.error)


class CodeGenSkill(Skill):
    """Generates code using an LLM driver."""

    @property
    def name(self) -> str:
        return "code_gen"

    @property
    def description(self) -> str:
        return "Generate code for a given task description."

    @property
    def parameters(self) -> list[SkillParam]:
        return [
            SkillParam(name="task", type="string", description="What code to write"),
            SkillParam(name="language", type="string", description="Programming language", required=False),
        ]

    async def execute(self, params: dict, process: Process, kernel: Kernel) -> SkillResult:
        task = params.get("task", "")
        lang = params.get("language", "Python")
        if not task:
            return SkillResult(success=False, error="Missing 'task'")

        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would generate {lang} code for: {task}")

        result = await driver.generate(
            [{"role": "user", "content": f"Write {lang} code: {task}. Output only code, no markdown."}],
            system="Output only raw code.",
        )
        if result.success:
            return SkillResult(success=True, data=result.data["text"].strip())
        return SkillResult(success=False, error=result.error)


class WebSearchSkill(Skill):
    """Searches the web using an HTTP driver."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web for information."

    @property
    def parameters(self) -> list[SkillParam]:
        return [
            SkillParam(name="query", type="string", description="Search query"),
        ]

    async def execute(self, params: dict, process: Process, kernel: Kernel) -> SkillResult:
        query = params.get("query", "")
        if not query:
            return SkillResult(success=False, error="Missing 'query'")
        return SkillResult(success=True, data=f"[mock] Would search: {query}")
