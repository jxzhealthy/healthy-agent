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

    def _build_tools(self, prompt: str = "") -> list[dict]:
        """Progressive disclosure: only expose relevant skills based on intent."""
        all_skills = list(self.skills._skills.values())

        if prompt:
            relevant = self._route_skills(prompt, all_skills)
        else:
            relevant = all_skills

        tools = []
        for skill in relevant:
            schema = skill.to_schema()
            tools.append({
                "name": schema["name"],
                "description": schema["description"],
                "input_schema": schema["parameters"],
            })
        logger.debug("Exposed %d/%d skills for prompt: %s", len(tools), len(all_skills), prompt[:50])
        return tools

    def _route_skills(self, prompt: str, all_skills: list) -> list:
        """Select relevant skills based on keyword matching against the prompt."""
        prompt_lower = prompt.lower()

        SKILL_KEYWORDS = {
            "read_file": ["read", "file", "open", "cat", "show", "content", "look at"],
            "write_file": ["write", "save", "create file", "output to"],
            "shell": ["run", "execute", "command", "terminal", "shell", "ls", "pwd", "pip"],
            "http_request": ["http", "url", "fetch", "api", "request", "download", "web"],
            "summarize": ["summarize", "summary", "tldr", "brief", "shorten"],
            "code_gen": ["code", "write", "implement", "function", "class", "script", "program"],
            "web_search": ["search", "google", "find", "lookup", "what is"],
        }

        matched = set()
        for skill in all_skills:
            keywords = SKILL_KEYWORDS.get(skill.name, [])
            if any(kw in prompt_lower for kw in keywords):
                matched.add(skill.name)

        if not matched:
            return all_skills[:3]

        return [s for s in all_skills if s.name in matched]

    async def run(
        self,
        prompt: str,
        *,
        context: str = "",
        on_step: Any = None,
    ) -> AgentResult:
        tools = self._build_tools(prompt)
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
