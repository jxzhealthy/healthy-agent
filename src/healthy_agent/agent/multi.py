from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from ..kernel.runtime import Kernel
from ..syscall import fork, wait

logger = logging.getLogger("healthy_agent.multi_agent")


@dataclass
class AgentConfig:
    name: str
    handler: Callable[..., Coroutine]
    payload: dict = field(default_factory=dict)


@dataclass
class MultiAgentResult:
    results: dict[str, Any] = field(default_factory=dict)
    total_agents: int = 0


class MultiAgentCoordinator:
    """Coordinate multiple agents running on the Kernel.

    Patterns:
      - parallel: all agents run concurrently
      - pipeline: agents run in sequence, output feeds next input
      - debate: agents discuss and reach consensus
    """

    def __init__(self, kernel: Kernel):
        self.kernel = kernel

    async def parallel(
        self,
        agents: list[AgentConfig],
        parent_process,
    ) -> MultiAgentResult:
        pids = {}
        for agent in agents:
            pid = await fork(
                self.kernel, parent_process, agent.name,
                agent.payload, handler=agent.handler,
            )
            pids[agent.name] = pid

        results = {}
        for name, pid in pids.items():
            results[name] = await wait(self.kernel, parent_process, pid)

        return MultiAgentResult(results=results, total_agents=len(agents))

    async def pipeline(
        self,
        agents: list[AgentConfig],
        parent_process,
        initial_input: Any = None,
    ) -> MultiAgentResult:
        results = {}
        current_input = initial_input

        for agent in agents:
            payload = dict(agent.payload)
            payload["_pipeline_input"] = current_input
            pid = await fork(
                self.kernel, parent_process, agent.name,
                payload, handler=agent.handler,
            )
            current_input = await wait(self.kernel, parent_process, pid)
            results[agent.name] = current_input

        return MultiAgentResult(results=results, total_agents=len(agents))

    async def debate(
        self,
        agents: list[AgentConfig],
        parent_process,
        topic: str,
        rounds: int = 3,
    ) -> MultiAgentResult:
        history: list[dict] = []
        results = {}

        for round_num in range(rounds):
            round_results = {}
            for agent in agents:
                payload = dict(agent.payload)
                payload["_debate_topic"] = topic
                payload["_debate_round"] = round_num
                payload["_debate_history"] = history
                pid = await fork(
                    self.kernel, parent_process, f"{agent.name}_r{round_num}",
                    payload, handler=agent.handler,
                )
                result = await wait(self.kernel, parent_process, pid)
                round_results[agent.name] = result
                history.append({"agent": agent.name, "round": round_num, "response": result})

            results[f"round_{round_num}"] = round_results

        results["final_history"] = history
        return MultiAgentResult(results=results, total_agents=len(agents))
