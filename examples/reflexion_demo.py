"""
Example 3: Reflexion - an agent that learns from its own mistakes.

Demonstrates:
  - ReflexionAgent: Execute -> Evaluate -> Reflect -> Retry
  - Custom evaluator function
  - Self-generated reflections improve subsequent attempts
  - The key difference from ReAct: agents learn WHY they failed

This example uses a mock driver that simulates:
  Trial 1: Generates wrong code -> evaluator rejects
  Trial 2: Gets reflection context -> generates correct code -> passes
"""
import asyncio
from healthy_agent.agent import ReflexionAgent, Evaluation
from healthy_agent.skill import SkillRegistry
from healthy_agent.drivers.base import LLMDriver, IOResult


class SimulatedDriver(LLMDriver):
    """Simulates an LLM that improves after receiving reflection feedback."""

    @property
    def name(self):
        return "simulated"

    async def generate(self, messages, **kwargs):
        content = str(messages)

        # Reflection prompt: generate structured self-critique
        if "WHAT_WENT_WRONG" in content:
            text = (
                "WHAT_WENT_WRONG: Returned input unchanged instead of sorting\n"
                "WHAT_TO_DO_DIFFERENTLY: Use two-pointer merge technique\n"
                "KEY_INSIGHT: Must compare elements and build new list"
            )
            return IOResult(success=True, data={"text": text, "tool_calls": [], "stop_reason": "end_turn"}, tokens_used=15)

        # After reflection: generate correct code
        if "Lessons from previous attempts" in content:
            code = (
                "def merge_sorted(a, b):\n"
                "    result = []\n"
                "    i = j = 0\n"
                "    while i < len(a) and j < len(b):\n"
                "        if a[i] <= b[j]:\n"
                "            result.append(a[i])\n"
                "            i += 1\n"
                "        else:\n"
                "            result.append(b[j])\n"
                "            j += 1\n"
                "    result.extend(a[i:])\n"
                "    result.extend(b[j:])\n"
                "    return result"
            )
            return IOResult(success=True, data={"text": code, "tool_calls": [], "stop_reason": "end_turn"}, tokens_used=20)

        # First attempt: wrong code
        wrong_code = "def merge_sorted(a, b):\n    return a + b  # BUG: not sorted!"
        return IOResult(success=True, data={"text": wrong_code, "tool_calls": [], "stop_reason": "end_turn"}, tokens_used=10)

    async def stream(self, messages, **kwargs):
        yield "mock"


async def code_evaluator(prompt: str, answer: str) -> Evaluation:
    """Evaluates whether the generated code actually merges sorted lists."""
    try:
        namespace = {}
        exec(answer, namespace)  # noqa: S102
        merge_fn = namespace.get("merge_sorted")
        if not merge_fn:
            return Evaluation(success=False, score=0.1, feedback="No merge_sorted function found")

        # Test cases
        tests = [
            ([1, 3, 5], [2, 4, 6], [1, 2, 3, 4, 5, 6]),
            ([], [1, 2], [1, 2]),
            ([1], [1], [1, 1]),
        ]
        for list_a, list_b, expected in tests:
            result = merge_fn(list_a, list_b)
            if result != expected:
                return Evaluation(
                    success=False, score=0.3,
                    feedback=f"merge_sorted({list_a}, {list_b}) = {result}, expected {expected}",
                )
        return Evaluation(success=True, score=1.0, feedback="All tests passed")
    except Exception as exc:
        return Evaluation(success=False, score=0.0, feedback=f"Runtime error: {exc}")


async def main():
    driver = SimulatedDriver()
    skills = SkillRegistry()

    agent = ReflexionAgent(
        driver=driver,
        skills=skills,
        evaluator=code_evaluator,
        max_trials=3,
        max_rounds=5,
    )

    print("=" * 50)
    print("  Reflexion Demo: Self-improving code generation")
    print("=" * 50)

    result = await agent.run("Write merge_sorted(a, b) that merges two sorted lists")

    print(f"\nSuccess: {result.success}")
    print(f"Trials: {result.total_trials}")
    print(f"Tokens: {result.total_tokens}")

    for trial in result.trials:
        status = "PASS" if trial.evaluation.success else "FAIL"
        print(f"\n--- Trial {trial.trial_number}: {status} (score={trial.evaluation.score}) ---")
        print(f"  Output: {trial.result.answer[:80]}...")
        if trial.evaluation.feedback:
            print(f"  Feedback: {trial.evaluation.feedback}")
        if trial.reflection:
            print(f"  Reflection: {trial.reflection.key_insight}")

    print(f"\nFinal answer:\n{result.answer}")


if __name__ == "__main__":
    asyncio.run(main())
