from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


class ProcessState(str, Enum):
    NEW = "new"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    TERMINATED = "terminated"


class BlockedError(Exception):
    def __init__(self, reason: str = "io"):
        self.reason = reason
        super().__init__(reason)


@dataclass
class PCB:
    pid: int
    parent_pid: int | None = None
    state: ProcessState = ProcessState.NEW
    priority: int = 0
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    cpu_time: float = 0.0
    time_slice: float = 0.1
    block_reason: str = ""
    context: dict = field(default_factory=dict)
    result: Any = None
    children: list[int] = field(default_factory=list)
    task_type: str = ""


class Process:
    def __init__(
        self,
        pid: int,
        task_type: str,
        payload: dict,
        handler: Callable[..., Coroutine] | None = None,
        parent_pid: int | None = None,
    ):
        self.pcb = PCB(pid=pid, parent_pid=parent_pid, task_type=task_type)
        self.task_type = task_type
        self.payload = payload
        self._handler = handler

    @property
    def pid(self) -> int:
        return self.pcb.pid

    @property
    def state(self) -> ProcessState:
        return self.pcb.state

    @state.setter
    def state(self, value: ProcessState) -> None:
        self.pcb.state = value

    async def execute(self, kernel: Any) -> Any:
        self.pcb.started_at = time.monotonic()
        if self._handler:
            return await self._handler(self, kernel)
        return None

    def block(self, reason: str = "") -> None:
        self.pcb.state = ProcessState.BLOCKED
        self.pcb.block_reason = reason

    def unblock(self) -> None:
        self.pcb.state = ProcessState.READY
        self.pcb.block_reason = ""

    def terminate(self, result: Any = None) -> None:
        self.pcb.state = ProcessState.TERMINATED
        self.pcb.result = result

    def __repr__(self) -> str:
        return f"Process(pid={self.pid}, type={self.task_type}, state={self.state.value})"
