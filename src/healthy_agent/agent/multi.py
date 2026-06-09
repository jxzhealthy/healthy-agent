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
        consensus_threshold: float = 0.5,
        summarizer: Callable[..., Coroutine] | None = None,
    ) -> MultiAgentResult:
        """Agents debate a topic over multiple rounds with consensus detection.

        Args:
            agents: List of agent configs to participate in debate.
            parent_process: Parent process for fork/wait.
            topic: The debate topic.
            rounds: Maximum number of debate rounds.
            consensus_threshold: Fraction of agents that must agree to reach consensus.
                                 Value between 0.0 and 1.0.
            summarizer: Optional async handler that receives debate history and produces
                        a final summary. If None, majority vote is used.
        """
        history: list[dict] = []
        results: dict[str, Any] = {}

        for round_num in range(rounds):
            round_results: dict[str, Any] = {}
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

            # --- Consensus check via majority vote ---
            consensus = _check_consensus(round_results, consensus_threshold)
            if consensus is not None:
                results["consensus"] = consensus
                results["consensus_round"] = round_num
                break

        results["final_history"] = history

        # --- Optional summarizer pass ---
        if summarizer and "consensus" not in results:
            summary_payload = {"_debate_history": history, "_debate_topic": topic}
            pid = await fork(
                self.kernel, parent_process, "debate_summarizer",
                summary_payload, handler=summarizer,
            )
            summary = await wait(self.kernel, parent_process, pid)
            results["summary"] = summary

        return MultiAgentResult(results=results, total_agents=len(agents))


def _check_consensus(
    round_results: dict[str, Any],
    threshold: float,
) -> Any | None:
    """Check if a majority of agents agree on the same result.

    Returns the consensus value if threshold is met, else None.
    Compares results by string representation for flexibility.
    """
    if not round_results:
        return None

    vote_counts: dict[str, int] = {}
    vote_values: dict[str, Any] = {}
    for result in round_results.values():
        key = str(result)
        vote_counts[key] = vote_counts.get(key, 0) + 1
        vote_values[key] = result

    total = len(round_results)
    for key, count in vote_counts.items():
        if count / total >= threshold:
            return vote_values[key]
    return None
