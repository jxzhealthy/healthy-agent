from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from ..kernel.runtime import Kernel
from ..syscall import fork, wait

logger = logging.getLogger("healthy_agent.workflow")


@dataclass
class WorkflowStep:
    name: str
    handler: Callable[..., Coroutine]
    depends_on: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    timeout: float | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class WorkflowResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    success: bool = True
    error: str = ""


class Workflow:
    """DAG-based workflow engine running on Kernel.

    Supports dependencies, conditional branching, step timeouts, and loops.

    Example:
        wf = Workflow(kernel)
        wf.add("fetch", fetch_handler)
        wf.add("parse", parse_handler, depends_on=["fetch"])
        wf.add("analyze", analyze_handler, depends_on=["fetch"],
               condition=lambda outputs: outputs.get("fetch") is not None)
        wf.add("report", report_handler, depends_on=["parse", "analyze"],
               timeout=30.0)
        result = await wf.execute(parent_process)
    """

    def __init__(self, kernel: Kernel):
        self.kernel = kernel
        self._steps: dict[str, WorkflowStep] = {}

    def add(
        self,
        name: str,
        handler: Callable[..., Coroutine],
        depends_on: list[str] | None = None,
        payload: dict | None = None,
        timeout: float | None = None,
        condition: Callable[[dict[str, Any]], bool] | None = None,
    ) -> Workflow:
        """Add a step to the workflow.

        Args:
            name: Unique step name.
            handler: Async handler to execute.
            depends_on: Steps that must complete before this one.
            payload: Static payload for the step.
            timeout: Max seconds for this step (None = no limit).
            condition: Predicate receiving current outputs dict.
                       Step is skipped if it returns False.
        """
        self._steps[name] = WorkflowStep(
            name=name,
            handler=handler,
            depends_on=depends_on or [],
            payload=payload or {},
            timeout=timeout,
            condition=condition,
        )
        return self

    async def execute(self, parent_process) -> WorkflowResult:
        outputs: dict[str, Any] = {}
        executed: set[str] = set()
        skipped: set[str] = set()
        order: list[str] = []

        all_names = set(self._steps)

        while len(executed | skipped) < len(self._steps):
            ready = [
                step for step in self._steps.values()
                if step.name not in executed
                and step.name not in skipped
                and all(d in (executed | skipped) for d in step.depends_on)
            ]

            if not ready:
                remaining = all_names - executed - skipped
                logger.error("Workflow deadlock: no steps ready, remaining=%s", remaining)
                return WorkflowResult(
                    outputs=outputs, execution_order=order,
                    skipped=sorted(skipped), success=False,
                    error=f"Deadlock: steps {remaining} cannot proceed",
                )

            # --- Evaluate conditions: skip steps whose condition is False ---
            runnable = []
            for step in ready:
                if step.condition is not None and not step.condition(outputs):
                    skipped.add(step.name)
                    logger.debug("Workflow step skipped (condition=False): %s", step.name)
                    continue
                runnable.append(step)

            if not runnable:
                continue

            # --- Fork all runnable steps in parallel ---
            pids: dict[str, int] = {}
            for step in runnable:
                payload = dict(step.payload)
                payload["_workflow_outputs"] = {
                    d: outputs.get(d) for d in step.depends_on
                }
                pid = await fork(
                    self.kernel, parent_process, f"wf:{step.name}",
                    payload, handler=step.handler,
                )
                pids[step.name] = pid

            # --- Wait for results with optional timeout ---
            for name, pid in pids.items():
                step = self._steps[name]
                try:
                    if step.timeout is not None:
                        result = await asyncio.wait_for(
                            wait(self.kernel, parent_process, pid),
                            timeout=step.timeout,
                        )
                    else:
                        result = await wait(self.kernel, parent_process, pid)
                except asyncio.TimeoutError:
                    result = TimeoutError(f"Step '{name}' timed out after {step.timeout}s")
                    logger.warning("Workflow step timed out: %s (%.1fs)", name, step.timeout)

                outputs[name] = result
                executed.add(name)
                order.append(name)
                logger.debug("Workflow step done: %s", name)

        return WorkflowResult(
            outputs=outputs, execution_order=order,
            skipped=sorted(skipped), success=True,
        )


class LoopWorkflow:
    """Execute a handler in a loop until a stop condition is met.

    Useful for iterative refinement or polling patterns.

    Example:
        loop = LoopWorkflow(kernel, max_iterations=5)
        result = await loop.execute(
            parent, handler=refine_handler,
            stop_condition=lambda result, i: result.get("quality") > 0.9,
        )
    """

    def __init__(self, kernel: Kernel, max_iterations: int = 10):
        self.kernel = kernel
        self.max_iterations = max_iterations

    async def execute(
        self,
        parent_process,
        handler: Callable[..., Coroutine],
        payload: dict | None = None,
        stop_condition: Callable[[Any, int], bool] | None = None,
        timeout_per_iteration: float | None = None,
    ) -> WorkflowResult:
        """Run handler repeatedly until stop_condition returns True.

        Args:
            parent_process: Parent process for fork/wait.
            handler: Async handler to run each iteration.
            payload: Base payload (augmented with iteration context).
            stop_condition: Callable(result, iteration) -> bool. Stops when True.
            timeout_per_iteration: Max seconds per iteration.
        """
        base_payload = payload or {}
        outputs: dict[str, Any] = {}
        order: list[str] = []
        last_result: Any = None

        for iteration in range(self.max_iterations):
            iter_payload = dict(base_payload)
            iter_payload["_loop_iteration"] = iteration
            iter_payload["_loop_previous_result"] = last_result

            step_name = f"loop_iter_{iteration}"
            pid = await fork(
                self.kernel, parent_process, step_name,
                iter_payload, handler=handler,
            )

            try:
                if timeout_per_iteration is not None:
                    result = await asyncio.wait_for(
                        wait(self.kernel, parent_process, pid),
                        timeout=timeout_per_iteration,
                    )
                else:
                    result = await wait(self.kernel, parent_process, pid)
            except asyncio.TimeoutError:
                result = TimeoutError(f"Loop iteration {iteration} timed out")
                logger.warning("Loop iteration %d timed out", iteration)

            last_result = result
            outputs[step_name] = result
            order.append(step_name)
            logger.debug("Loop iteration %d done", iteration)

            if stop_condition and stop_condition(result, iteration):
                logger.debug("Loop stop condition met at iteration %d", iteration)
                break

        return WorkflowResult(
            outputs=outputs, execution_order=order, success=True,
        )
