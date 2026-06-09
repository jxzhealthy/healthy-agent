from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..drivers.base import LLMDriver
from ..skill.registry import SkillRegistry

logger = logging.getLogger("healthy_agent.agent")


@dataclass
class AgentStep:
    role: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_result: str = ""


@dataclass
class AgentResult:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    total_rounds: int = 0
    tokens_used: int = 0


class AgentLoop:
    """Agentic loop: LLM decides which tools to call, executes them, loops until done.

    Similar to ReAct but with OS-level scheduling underneath.
    """

    def __init__(
        self,
        driver: LLMDriver,
        skills: SkillRegistry,
        *,
        max_rounds: int = 10,
        system_prompt: str = "",
    ):
        self.driver = driver
        self.skills = skills
        self.max_rounds = max_rounds
        self.system_prompt = system_prompt or (
            "You are a helpful assistant with access to tools. "
            "Use tools when needed to answer the user's question. "
            "When you have enough information, respond directly."
        )

    def _build_tools(self) -> list[dict]:
        tools = []
        for schema in self.skills.list_skills():
            tools.append({
                "name": schema["name"],
                "description": schema["description"],
                "input_schema": schema["parameters"],
            })
        return tools

    async def run(
        self,
        prompt: str,
        *,
        context: str = "",
        on_step: Any = None,
    ) -> AgentResult:
        tools = self._build_tools()
        messages = []
        if context:
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "Understood."})
        messages.append({"role": "user", "content": prompt})

        steps: list[AgentStep] = []
        tokens = 0

        for round_num in range(1, self.max_rounds + 1):
            result = await self.driver.generate(
                messages,
                system=self.system_prompt,
                tools=tools if tools else None,
            )
            tokens += result.tokens_used

            if not result.success:
                return AgentResult(answer=f"ERROR: {result.error}", steps=steps, total_rounds=round_num, tokens_used=tokens)

            text = result.data.get("text", "")
            tool_calls = result.data.get("tool_calls", [])
            stop_reason = result.data.get("stop_reason", "")

            if text:
                steps.append(AgentStep(role="assistant", content=text))
                if on_step:
                    on_step(steps[-1])

            if not tool_calls or stop_reason != "tool_use":
                return AgentResult(answer=text, steps=steps, total_rounds=round_num, tokens_used=tokens)

            assistant_content = []
            if text:
                assistant_content.append({"type": "text", "text": text})
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in tool_calls:
                logger.info("Tool call: %s(%s)", tc["name"], tc["input"])
                step = AgentStep(role="tool", tool_name=tc["name"], tool_input=tc["input"])

                skill_result = await self.skills.invoke(tc["name"], tc["input"], None, None)
                step.tool_result = str(skill_result.data) if skill_result.success else f"ERROR: {skill_result.error}"

                steps.append(step)
                if on_step:
                    on_step(step)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": step.tool_result,
                })

            messages.append({"role": "user", "content": tool_results})

        return AgentResult(answer="Max rounds reached", steps=steps, total_rounds=self.max_rounds, tokens_used=tokens)
