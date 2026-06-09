"""
Example 2: Executor + Skills - tool-augmented task execution.

Demonstrates:
  - Executor as the low-level execution engine
  - Custom Skill registration
  - Mock LLM driver for offline testing
  - Progressive skill routing via TF-IDF
"""
import asyncio
from healthy_agent.execution import Executor
from healthy_agent.skill import SkillRegistry
from healthy_agent.skill.base import Skill, SkillParam, SkillResult
from healthy_agent.drivers.base import LLMDriver, IOResult


class MockDriver(LLMDriver):
    """Returns canned responses that exercise tool calling."""

    @property
    def name(self):
        return "mock"

    async def generate(self, messages, **kwargs):
        last = str(messages[-1].get("content", ""))

        # If this is a tool result, wrap up
        if "tool_result" in last or isinstance(messages[-1].get("content"), list):
            return IOResult(
                success=True,
                data={"text": "Done! The result is ready.", "tool_calls": [], "stop_reason": "end_turn"},
                tokens_used=5,
            )

        # First call: invoke the calculator
        return IOResult(
            success=True,
            data={
                "text": "Let me calculate that for you.",
                "tool_calls": [{"id": "tc1", "name": "calculate", "input": {"expression": "42 * 58"}}],
                "stop_reason": "tool_use",
            },
            tokens_used=10,
        )

    async def stream(self, messages, **kwargs):
        yield "mock stream"


class CalculatorSkill(Skill):
    @property
    def name(self):
        return "calculate"

    @property
    def description(self):
        return "Evaluate a math expression"

    @property
    def parameters(self):
        return [SkillParam(name="expression", type="string", description="Math expression to evaluate")]

    async def execute(self, params, process, kernel):
        expr = params.get("expression", "0")
        try:
            result = eval(expr, {"__builtins__": {}})  # noqa: S307
            return SkillResult(success=True, data=str(result))
        except Exception as exc:
            return SkillResult(success=False, error=str(exc))


class GreetSkill(Skill):
    @property
    def name(self):
        return "greet"

    @property
    def description(self):
        return "Greet a user by name"

    @property
    def parameters(self):
        return [SkillParam(name="name", type="string", description="Name to greet")]

    async def execute(self, params, process, kernel):
        return SkillResult(success=True, data=f"Hello, {params.get('name', 'World')}!")


async def main():
    driver = MockDriver()
    skills = SkillRegistry()
    skills.register(CalculatorSkill())
    skills.register(GreetSkill())

    executor = Executor(driver, skills, max_rounds=5)
    result = await executor.run("What is 42 times 58?")

    print(f"Answer: {result.answer}")
    print(f"Rounds: {result.total_rounds}")
    print(f"Tokens: {result.tokens_used}")
    print("\nSteps:")
    for step in result.steps:
        if step.role == "assistant":
            print(f"  [assistant] {step.content}")
        elif step.role == "tool":
            print(f"  [tool] {step.tool_name}({step.tool_input}) -> {step.tool_result}")


if __name__ == "__main__":
    asyncio.run(main())
