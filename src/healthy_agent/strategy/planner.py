"""Plan-then-Execute: a strategy that plans before acting.

Instead of ReAct's step-by-step improvisation, this strategy:
  1. Ask LLM to generate a full plan (list of steps)
  2. Execute each step sequentially via Executor
  3. Optionally re-plan if a step fails

This is the second strategy layer alongside Reflexion.

Example:
    planner = PlanExecuteAgent(driver, skills, max_steps=5)
    result = await planner.run("Research AI safety and write a summary report")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..execution.executor import Executor, AgentResult

logger = logging.getLogger("healthy_agent.strategy.planner")


PLAN_PROMPT = """Break down the following task into a numbered list of concrete steps.
Each step should be a single, actionable instruction that can be executed independently.
Output ONLY a JSON array of strings, no other text.

Task: {task}

Example output:
["Step 1: ...", "Step 2: ...", "Step 3: ..."]"""

REPLAN_PROMPT = """The original task was: {task}

The plan so far:
{completed_steps}

Step {failed_step_num} failed:
  Step: {failed_step}
  Error: {error}

Please generate a revised plan for the REMAINING work.
Output ONLY a JSON array of strings for the remaining steps."""


@dataclass
class StepResult:
    step_index: int
    step_description: str
    result: AgentResult
    success: bool


@dataclass
class PlanExecuteResult:
    success: bool
    answer: str
    plan: list[str] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    replanned: bool = False
    total_tokens: int = 0


def _parse_plan(text: str) -> list[str]:
    """Extract a JSON array of steps from LLM output."""
    text = text.strip()
    # Find JSON array in the response
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            steps = json.loads(text[start:end + 1])
            if isinstance(steps, list):
                return [str(s) for s in steps if s]
        except json.JSONDecodeError:
            pass
    # Fallback: split by newlines and numbered patterns
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    steps = []
    for line in lines:
        # Remove numbering like "1.", "1)", "Step 1:"
        cleaned = line.lstrip("0123456789.-) ").strip()
        if cleaned.startswith(":"):
            cleaned = cleaned[1:].strip()
        if cleaned:
            steps.append(cleaned)
    return steps or [text]


class PlanExecuteAgent:
    """Strategy that generates a plan first, then executes step by step.

    Args:
        driver: LLM driver for generation.
        skills: Tool registry.
        max_steps: Maximum steps in a plan.
        max_rounds_per_step: Max tool-calling rounds per step (passed to Executor).
        system_prompt: Base system prompt for execution.
        allow_replan: If True, re-plan when a step fails instead of aborting.
        planner_driver: Optional separate driver for planning (can use stronger model).
    """

    def __init__(
        self,
        driver: Any,
        skills: Any,
        *,
        max_steps: int = 10,
        max_rounds_per_step: int = 5,
        system_prompt: str = "",
        allow_replan: bool = True,
        planner_driver: Any = None,
    ):
        self.driver = driver
        self.skills = skills
        self.max_steps = max_steps
        self.max_rounds_per_step = max_rounds_per_step
        self.system_prompt = system_prompt
        self.allow_replan = allow_replan
        self.planner_driver = planner_driver or driver

    async def run(
        self,
        task: str,
        *,
        on_plan: Callable[[list[str]], Any] | None = None,
        on_step: Callable[[StepResult], Any] | None = None,
    ) -> PlanExecuteResult:
        """Execute a task using plan-then-execute strategy.

        Args:
            task: The task to accomplish.
            on_plan: Callback when plan is generated/revised.
            on_step: Callback after each step completes.
        """
        total_tokens = 0

        # --- Phase 1: Generate plan ---
        plan = await self._generate_plan(task)
        total_tokens += 10  # estimate
        if not plan:
            return PlanExecuteResult(
                success=False, answer="Failed to generate a plan",
                plan=[], total_tokens=total_tokens,
            )

        plan = plan[:self.max_steps]
        logger.info("Plan generated: %d steps", len(plan))
        if on_plan:
            on_plan(plan)

        # --- Phase 2: Execute steps ---
        step_results: list[StepResult] = []
        completed_context = ""
        replanned = False

        for idx, step_desc in enumerate(plan):
            logger.info("Executing step %d/%d: %s", idx + 1, len(plan), step_desc[:80])

            context = f"Overall task: {task}\n\n"
            if completed_context:
                context += f"Completed so far:\n{completed_context}\n\n"
            context += f"Current step ({idx + 1}/{len(plan)}): {step_desc}"

            executor = Executor(
                self.driver, self.skills,
                max_rounds=self.max_rounds_per_step,
                system_prompt=self.system_prompt,
            )
            agent_result = await executor.run(step_desc, context=context)
            total_tokens += agent_result.tokens_used

            is_success = not agent_result.answer.startswith("ERROR") and agent_result.answer != "Max rounds reached"

            step_result = StepResult(
                step_index=idx,
                step_description=step_desc,
                result=agent_result,
                success=is_success,
            )
            step_results.append(step_result)

            if on_step:
                on_step(step_result)

            if is_success:
                completed_context += f"\n- Step {idx + 1}: {step_desc} -> {agent_result.answer[:200]}"
            elif self.allow_replan and idx < len(plan) - 1:
                # Re-plan remaining steps
                logger.info("Step %d failed, re-planning...", idx + 1)
                new_plan = await self._replan(
                    task, completed_context, idx + 1, step_desc, agent_result.answer,
                )
                total_tokens += 10
                if new_plan:
                    replanned = True
                    remaining = new_plan[:self.max_steps - idx - 1]
                    plan = [s.step_description for s in step_results] + remaining
                    if on_plan:
                        on_plan(remaining)
                    # Continue with new plan by extending the loop
                    for new_idx, new_step in enumerate(remaining):
                        logger.info("Re-plan step %d: %s", new_idx + 1, new_step[:80])
                        new_context = f"Overall task: {task}\n\nCompleted:\n{completed_context}\n\nCurrent step: {new_step}"
                        new_executor = Executor(
                            self.driver, self.skills,
                            max_rounds=self.max_rounds_per_step,
                            system_prompt=self.system_prompt,
                        )
                        new_result = await new_executor.run(new_step, context=new_context)
                        total_tokens += new_result.tokens_used
                        new_is_success = not new_result.answer.startswith("ERROR")
                        new_step_result = StepResult(
                            step_index=len(step_results),
                            step_description=new_step,
                            result=new_result,
                            success=new_is_success,
                        )
                        step_results.append(new_step_result)
                        if on_step:
                            on_step(new_step_result)
                        if new_is_success:
                            completed_context += f"\n- {new_step} -> {new_result.answer[:200]}"
                    break
                else:
                    break
            else:
                break

        # --- Phase 3: Synthesize final answer ---
        all_success = all(sr.success for sr in step_results)
        if step_results:
            final_answer = step_results[-1].result.answer
        else:
            final_answer = "No steps executed"

        return PlanExecuteResult(
            success=all_success,
            answer=final_answer,
            plan=plan,
            step_results=step_results,
            replanned=replanned,
            total_tokens=total_tokens,
        )

    async def _generate_plan(self, task: str) -> list[str]:
        prompt = PLAN_PROMPT.format(task=task)
        result = await self.planner_driver.generate(
            [{"role": "user", "content": prompt}],
            system="You are a task planner. Break tasks into clear, actionable steps.",
        )
        if not result.success:
            return []
        return _parse_plan(result.data.get("text", ""))

    async def _replan(
        self, task: str, completed: str, failed_num: int, failed_step: str, error: str,
    ) -> list[str]:
        prompt = REPLAN_PROMPT.format(
            task=task,
            completed_steps=completed or "(none)",
            failed_step_num=failed_num,
            failed_step=failed_step,
            error=error[:500],
        )
        result = await self.planner_driver.generate(
            [{"role": "user", "content": prompt}],
            system="You are a task planner. Revise the plan based on what happened.",
        )
        if not result.success:
            return []
        return _parse_plan(result.data.get("text", ""))
