from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from .process import Process, ProcessState

DEFAULT_TIME_SLICES = [0.5, 2.0, 10.0, float("inf")]


@dataclass
class SchedulerStats:
    queue_lengths: list[int]
    total_scheduled: int
    total_preempted: int
    total_boosted: int


class MLFQScheduler:
    def __init__(
        self,
        num_levels: int = 4,
        time_slices: list[float] | None = None,
        boost_interval: float = 30.0,
    ):
        self.num_levels = num_levels
        self.time_slices = time_slices or DEFAULT_TIME_SLICES[:num_levels]
        self.boost_interval = boost_interval
        self.queues: list[deque[Process]] = [deque() for _ in range(num_levels)]
        self._last_boost = time.monotonic()
        self._stats = {"scheduled": 0, "preempted": 0, "boosted": 0}

    def admit(self, process: Process) -> None:
        process.pcb.priority = 0
        process.pcb.time_slice = self.time_slices[0]
        process.pcb.state = ProcessState.READY
        self.queues[0].append(process)

    def schedule(self) -> Process | None:
        self._maybe_boost()
        for queue in self.queues:
            if queue:
                p = queue.popleft()
                p.pcb.state = ProcessState.RUNNING
                self._stats["scheduled"] += 1
                return p
        return None

    def preempt(self, process: Process) -> None:
        level = min(process.pcb.priority + 1, self.num_levels - 1)
        process.pcb.priority = level
        process.pcb.time_slice = self.time_slices[level]
        process.pcb.state = ProcessState.READY
        self.queues[level].append(process)
        self._stats["preempted"] += 1

    def unblock(self, process: Process) -> None:
        level = process.pcb.priority
        process.pcb.time_slice = self.time_slices[level]
        process.pcb.state = ProcessState.READY
        self.queues[level].append(process)

    def boost(self) -> None:
        for level in range(1, self.num_levels):
            while self.queues[level]:
                p = self.queues[level].popleft()
                p.pcb.priority = 0
                p.pcb.time_slice = self.time_slices[0]
                self.queues[0].append(p)
        self._last_boost = time.monotonic()
        self._stats["boosted"] += 1

    def _maybe_boost(self) -> None:
        if time.monotonic() - self._last_boost >= self.boost_interval:
            self.boost()

    @property
    def total_ready(self) -> int:
        return sum(len(q) for q in self.queues)

    @property
    def is_empty(self) -> bool:
        return self.total_ready == 0

    def stats(self) -> SchedulerStats:
        return SchedulerStats(
            queue_lengths=[len(q) for q in self.queues],
            total_scheduled=self._stats["scheduled"],
            total_preempted=self._stats["preempted"],
            total_boosted=self._stats["boosted"],
        )
