from __future__ import annotations

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


@dataclass
class WorkflowResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    success: bool = True


class Workflow:
    """DAG-based workflow engine running on Kernel.

    Steps declare dependencies. Independent steps run in parallel.

    Example:
        wf = Workflow(kernel)
        wf.add("fetch", fetch_handler)
        wf.add("parse", parse_handler, depends_on=["fetch"])
        wf.add("analyze", analyze_handler, depends_on=["fetch"])
        wf.add("report", report_handler, depends_on=["parse", "analyze"])
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
    ) -> Workflow:
        self._steps[name] = WorkflowStep(
            name=name,
            handler=handler,
            depends_on=depends_on or [],
            payload=payload or {},
        )
        return self

    async def execute(self, parent_process) -> WorkflowResult:
        outputs: dict[str, Any] = {}
        executed: set[str] = set()
        order: list[str] = []

        while len(executed) < len(self._steps):
            ready = [
                step for step in self._steps.values()
                if step.name not in executed
                and all(d in executed for d in step.depends_on)
            ]

            if not ready:
                logger.error("Workflow deadlock: no steps ready, executed=%s", executed)
                return WorkflowResult(outputs=outputs, execution_order=order, success=False)

            pids = {}
            for step in ready:
                payload = dict(step.payload)
                payload["_workflow_outputs"] = {d: outputs[d] for d in step.depends_on}
                pid = await fork(
                    self.kernel, parent_process, f"wf:{step.name}",
                    payload, handler=step.handler,
                )
                pids[step.name] = pid

            for name, pid in pids.items():
                result = await wait(self.kernel, parent_process, pid)
                outputs[name] = result
                executed.add(name)
                order.append(name)
                logger.debug("Workflow step done: %s", name)

        return WorkflowResult(outputs=outputs, execution_order=order, success=True)
