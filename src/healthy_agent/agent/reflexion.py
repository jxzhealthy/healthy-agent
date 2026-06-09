"""Reflexion: an agent framework that learns from trial and error.

Instead of ReAct's linear Think-Act-Observe, Reflexion adds:
  Execute -> Evaluate -> Reflect -> Retry (with reflection memory)

The key insight: feeding self-generated "lessons learned" back into
the prompt dramatically improves success rate on subsequent attempts.

Reference: Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning"

Example:
    driver = AnthropicDriver(model="claude-sonnet-4-20250514")
    skills = SkillRegistry()

    reflexion = ReflexionAgent(
        driver=driver,
        skills=skills,
        evaluator=code_test_evaluator,  # runs tests, returns pass/fail + feedback
        max_trials=3,
    )
    result = await reflexion.run("Write a function that sorts a list using merge sort")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from .executor import Executor, AgentResult

logger = logging.getLogger("healthy_agent.reflexion")


@dataclass
class Evaluation:
    """Result of evaluating an agent's output."""
    success: bool
    score: float = 0.0          # 0.0 ~ 1.0
    feedback: str = ""          # What went wrong / what was good
    details: dict = field(default_factory=dict)


@dataclass
class Reflection:
    """A self-generated lesson from a failed attempt."""
    trial: int
    what_went_wrong: str
    what_to_do_differently: str
    key_insight: str


@dataclass
class Trial:
    """Record of a single attempt."""
    trial_number: int
    result: AgentResult
    evaluation: Evaluation
    reflection: Reflection | None = None


@dataclass
class ReflexionResult:
    """Final result of the Reflexion loop."""
    success: bool
    answer: str
    trials: list[Trial] = field(default_factory=list)
    total_trials: int = 0
    total_tokens: int = 0
    reflections: list[Reflection] = field(default_factory=list)


# Type alias for evaluator functions
Evaluator = Callable[[str, str], Coroutine[Any, Any, Evaluation]]
# evaluator(prompt, agent_answer) -> Evaluation


REFLECT_PROMPT = """You are analyzing a failed attempt at solving a task.

Task: {task}

My previous answer:
{answer}

Evaluation feedback:
{feedback}

Score: {score}/1.0

Please reflect on this attempt and provide:
1. WHAT_WENT_WRONG: What specific error or weakness led to the failure?
2. WHAT_TO_DO_DIFFERENTLY: What concrete strategy should be used in the next attempt?
3. KEY_INSIGHT: One sentence capturing the most important lesson learned.

Respond in this exact format:
WHAT_WENT_WRONG: <your analysis>
WHAT_TO_DO_DIFFERENTLY: <your strategy>
KEY_INSIGHT: <one sentence>"""


def _parse_reflection(text: str, trial: int) -> Reflection:
    """Parse the LLM's reflection response into structured data."""
    lines = text.strip().split("\n")
    what_wrong = ""
    what_different = ""
    insight = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("WHAT_WENT_WRONG:"):
            what_wrong = stripped[len("WHAT_WENT_WRONG:"):].strip()
        elif stripped.startswith("WHAT_TO_DO_DIFFERENTLY:"):
            what_different = stripped[len("WHAT_TO_DO_DIFFERENTLY:"):].strip()
        elif stripped.startswith("KEY_INSIGHT:"):
            insight = stripped[len("KEY_INSIGHT:"):].strip()

    return Reflection(
        trial=trial,
        what_went_wrong=what_wrong or "Unable to determine",
        what_to_do_differently=what_different or "Try a different approach",
        key_insight=insight or "Review the requirements more carefully",
    )


def _build_reflection_context(reflections: list[Reflection]) -> str:
    """Build a context string from accumulated reflections."""
    if not reflections:
        return ""

    parts = ["## Lessons from previous attempts\n"]
    for ref in reflections:
        parts.append(
            f"### Attempt {ref.trial}\n"
            f"- **Problem**: {ref.what_went_wrong}\n"
            f"- **Strategy**: {ref.what_to_do_differently}\n"
            f"- **Insight**: {ref.key_insight}\n"
        )
    parts.append(
        "Use these lessons to avoid repeating the same mistakes. "
        "Apply the strategies suggested above."
    )
    return "\n".join(parts)


class ReflexionAgent:
    """Agent that learns from its own mistakes through self-reflection.

    Flow:
        Trial 1: Execute task → Evaluate → (if fail) Reflect
        Trial 2: Execute with reflections in context → Evaluate → (if fail) Reflect
        Trial 3: Execute with all reflections → Evaluate → ...
        Until success or max_trials reached.

    Args:
        driver: LLM driver for generation.
        skills: Tool registry.
        evaluator: Async function(prompt, answer) -> Evaluation.
        max_trials: Maximum number of attempts.
        max_rounds: Max tool-calling rounds per trial (passed to Executor).
        system_prompt: Base system prompt.
        reflect_model: Optional separate driver for reflection (can use cheaper model).
        success_threshold: Minimum score to consider success (0.0-1.0).
    """

    def __init__(
        self,
        driver: Any,
        skills: Any,
        evaluator: Evaluator,
        *,
        max_trials: int = 3,
        max_rounds: int = 10,
        system_prompt: str = "",
        reflect_model: Any = None,
        success_threshold: float = 1.0,
    ):
        self.driver = driver
        self.skills = skills
        self.evaluator = evaluator
        self.max_trials = max_trials
        self.max_rounds = max_rounds
        self.system_prompt = system_prompt
        self.reflect_driver = reflect_model or driver
        self.success_threshold = success_threshold

    async def run(
        self,
        prompt: str,
        *,
        on_trial: Callable[[Trial], Any] | None = None,
        on_reflection: Callable[[Reflection], Any] | None = None,
    ) -> ReflexionResult:
        """Execute the Reflexion loop.

        Args:
            prompt: The task to solve.
            on_trial: Optional callback after each trial.
            on_reflection: Optional callback after each reflection.
        """
        reflections: list[Reflection] = []
        trials: list[Trial] = []
        total_tokens = 0

        for trial_num in range(1, self.max_trials + 1):
            logger.info("Reflexion trial %d/%d", trial_num, self.max_trials)

            # --- 1. Build context from past reflections ---
            reflection_context = _build_reflection_context(reflections)

            # --- 2. Execute (run Executor with reflection context) ---
            executor = Executor(
                self.driver,
                self.skills,
                max_rounds=self.max_rounds,
                system_prompt=self.system_prompt,
            )
            agent_result = await executor.run(prompt, context=reflection_context)
            total_tokens += agent_result.tokens_used

            # --- 3. Evaluate ---
            evaluation = await self.evaluator(prompt, agent_result.answer)
            logger.info(
                "Trial %d: score=%.2f success=%s feedback=%s",
                trial_num, evaluation.score, evaluation.success, evaluation.feedback[:100],
            )

            trial = Trial(
                trial_number=trial_num,
                result=agent_result,
                evaluation=evaluation,
            )

            # --- 4. Check success ---
            if evaluation.success or evaluation.score >= self.success_threshold:
                trials.append(trial)
                if on_trial:
                    _maybe_await(on_trial, trial)
                return ReflexionResult(
                    success=True,
                    answer=agent_result.answer,
                    trials=trials,
                    total_trials=trial_num,
                    total_tokens=total_tokens,
                    reflections=reflections,
                )

            # --- 5. Reflect (generate lesson from failure) ---
            if trial_num < self.max_trials:
                reflection = await self._reflect(
                    prompt, agent_result.answer, evaluation, trial_num,
                )
                total_tokens += reflection_tokens_estimate(reflection)
                trial.reflection = reflection
                reflections.append(reflection)

                logger.info(
                    "Reflection %d: insight=%s",
                    trial_num, reflection.key_insight,
                )
                if on_reflection:
                    _maybe_await(on_reflection, reflection)

            trials.append(trial)
            if on_trial:
                _maybe_await(on_trial, trial)

        # All trials exhausted — return best attempt
        best_trial = max(trials, key=lambda t: t.evaluation.score)
        return ReflexionResult(
            success=False,
            answer=best_trial.result.answer,
            trials=trials,
            total_trials=len(trials),
            total_tokens=total_tokens,
            reflections=reflections,
        )

    async def _reflect(
        self,
        task: str,
        answer: str,
        evaluation: Evaluation,
        trial_num: int,
    ) -> Reflection:
        """Generate a self-reflection from a failed attempt."""
        reflect_prompt = REFLECT_PROMPT.format(
            task=task,
            answer=answer[:2000],
            feedback=evaluation.feedback,
            score=evaluation.score,
        )

        result = await self.reflect_driver.generate(
            [{"role": "user", "content": reflect_prompt}],
            system="You are a thoughtful analyst. Provide specific, actionable reflections.",
        )

        if result.success:
            return _parse_reflection(result.data.get("text", ""), trial_num)

        return Reflection(
            trial=trial_num,
            what_went_wrong=f"Previous attempt failed: {evaluation.feedback}",
            what_to_do_differently="Try a completely different approach",
            key_insight="The previous strategy did not work",
        )


def reflection_tokens_estimate(reflection: Reflection) -> int:
    """Rough token estimate for a reflection (for tracking)."""
    text = reflection.what_went_wrong + reflection.what_to_do_differently + reflection.key_insight
    return len(text.split()) * 2


def _maybe_await(callback: Callable, *args: Any) -> None:
    """Call a callback, handling both sync and async."""
    import asyncio
    result = callback(*args)
    if asyncio.iscoroutine(result):
        asyncio.ensure_future(result)
