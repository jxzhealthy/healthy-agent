from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Coroutine

from .process import Process, ProcessState
from .scheduler import MLFQScheduler
from .core import Core
from ..observability.metrics import metrics

logger = logging.getLogger("healthy_agent.kernel")


class ResourceError(RuntimeError):
    """Raised when a kernel resource limit is exceeded."""
    pass


class Kernel:
    def __init__(
        self,
        num_cores: int = 4,
        boost_interval: float = 30.0,
        max_processes: int = 1000,
        max_spawn_rate: float = 100.0,
    ):
        """Initialize the Kernel.

        Args:
            num_cores: Number of concurrent execution cores.
            boost_interval: MLFQ priority boost interval in seconds.
            max_processes: Maximum number of live processes (non-terminated).
                           Spawn will raise if exceeded.
            max_spawn_rate: Maximum spawns per second (rate limiting).
        """
        self.scheduler = MLFQScheduler(boost_interval=boost_interval)
        self.num_cores = num_cores
        self.cores: list[Core] = [Core(i, self) for i in range(num_cores)]
        self.process_table: dict[int, Process] = {}
        self._pid_counter = 0
        self._active_count = 0  # O(1) active process counter
        self._events: dict[int, asyncio.Event] = {}
        self._waiters: dict[int, int] = {}
        self._shutdown = asyncio.Event()
        self._work_available = asyncio.Event()  # Signal cores when work is ready
        self._reap_queue: list[tuple[float, int]] = []
        self._reap_ttl = 60.0
        self._start_time = time.monotonic()
        # Resource limits
        self._max_processes = max_processes
        self._max_spawn_rate = max_spawn_rate
        self._spawn_timestamps: deque[float] = deque()  # O(1) popleft

    def spawn(
        self,
        task_type: str,
        payload: dict,
        handler: Callable[..., Coroutine] | None = None,
        parent_pid: int | None = None,
        preemptible: bool = True,
    ) -> int:
        # Resource limit: max processes (O(1) check)
        if self._active_count >= self._max_processes:
            self.reap()
            if self._active_count >= self._max_processes:
                raise ResourceError(
                    f"Max processes exceeded: {self._active_count}/{self._max_processes}"
                )

        # Resource limit: spawn rate (O(1) amortized with deque)
        now = time.monotonic()
        cutoff = now - 1.0
        while self._spawn_timestamps and self._spawn_timestamps[0] < cutoff:
            self._spawn_timestamps.popleft()
        if len(self._spawn_timestamps) >= self._max_spawn_rate:
            raise ResourceError(
                f"Spawn rate exceeded: {len(self._spawn_timestamps)}/{self._max_spawn_rate} per second"
            )
        self._spawn_timestamps.append(now)

        self._pid_counter += 1
        pid = self._pid_counter
        process = Process(pid, task_type, payload, handler=handler, parent_pid=parent_pid)
        self.process_table[pid] = process
        self._active_count += 1
        if parent_pid is not None:
            parent = self.process_table.get(parent_pid)
            if parent:
                parent.pcb.children.append(pid)
        self.scheduler.admit(process)
        if not preemptible:
            process.pcb.time_slice = float("inf")
        # Signal cores that work is available
        self._work_available.set()
        metrics.increment("kernel.spawns", tags={"type": task_type})
        metrics.gauge("kernel.active_processes", self._active_count)
        logger.debug("spawn pid=%d type=%s parent=%s preemptible=%s", pid, task_type, parent_pid, preemptible)
        return pid

    async def run(self) -> None:
        logger.info("Kernel starting with %d cores", self.num_cores)
        self._shutdown.clear()
        tasks = [asyncio.create_task(core.run_loop()) for core in self.cores]
        await self._shutdown.wait()
        for core in self.cores:
            core.stop()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def exec(self, pid: int) -> Any:
        self._shutdown.clear()
        core_tasks = [asyncio.create_task(core.run_loop()) for core in self.cores]
        event = self._get_event(pid)
        await event.wait()
        result = self.process_table[pid].pcb.result if pid in self.process_table else None
        self._shutdown.set()
        for core in self.cores:
            core.stop()
        await asyncio.gather(*core_tasks, return_exceptions=True)
        return result

    async def wait_pid(self, pid: int) -> Any:
        event = self._get_event(pid)
        await event.wait()
        return self.process_table[pid].pcb.result

    def _get_event(self, pid: int) -> asyncio.Event:
        if pid not in self._events:
            self._events[pid] = asyncio.Event()
        return self._events[pid]

    def _complete(self, process: Process, result: Any) -> None:
        process.pcb.state = ProcessState.TERMINATED
        process.pcb.result = result
        self._active_count -= 1
        metrics.increment("kernel.completed", tags={"type": process.task_type})
        metrics.record_latency("kernel.process_cpu", process.pcb.cpu_time, tags={"type": process.task_type})
        if isinstance(result, Exception):
            metrics.increment("kernel.errors")
            logger.warning("pid=%d type=%s terminated with error: %s", process.pid, process.task_type, result)
        else:
            logger.debug("pid=%d type=%s terminated cpu=%.4fs", process.pid, process.task_type, process.pcb.cpu_time)
        self._get_event(process.pid).set()
        waiter_pid = self._waiters.pop(process.pid, None)
        if waiter_pid is not None:
            waiter = self.process_table.get(waiter_pid)
            if waiter and waiter.state == ProcessState.BLOCKED:
                waiter.pcb.context["wait_result"] = result
                self.scheduler.unblock(waiter)
                self._work_available.set()
        self._reap_queue.append((time.monotonic() + self._reap_ttl, process.pid))

    def io_complete(self, process: Process, result: Any = None) -> None:
        if process.state != ProcessState.BLOCKED:
            return
        process.pcb.context["io_result"] = result
        self.scheduler.unblock(process)
        self._work_available.set()

    def reap(self) -> int:
        now = time.monotonic()
        reaped = 0
        remaining = []
        for deadline, pid in self._reap_queue:
            if now >= deadline:
                self.process_table.pop(pid, None)
                self._events.pop(pid, None)
                reaped += 1
            else:
                remaining.append((deadline, pid))
        self._reap_queue = remaining
        if reaped:
            logger.debug("reaped %d terminated processes", reaped)
        return reaped

    def shutdown(self) -> None:
        logger.info("Kernel shutting down, %d processes total", len(self.process_table))
        self._shutdown.set()

    def ps(self) -> list[dict]:
        return [
            {
                "pid": p.pid,
                "type": p.task_type,
                "state": p.state.value,
                "priority": p.pcb.priority,
                "cpu_time": round(p.pcb.cpu_time, 4),
                "parent": p.pcb.parent_pid,
            }
            for p in self.process_table.values()
        ]
