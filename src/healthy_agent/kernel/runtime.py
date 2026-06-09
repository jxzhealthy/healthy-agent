from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine

from .process import Process, ProcessState
from .scheduler import MLFQScheduler
from .core import Core


class Kernel:
    def __init__(self, num_cores: int = 4, boost_interval: float = 30.0):
        self.scheduler = MLFQScheduler(boost_interval=boost_interval)
        self.num_cores = num_cores
        self.cores: list[Core] = [Core(i, self) for i in range(num_cores)]
        self.process_table: dict[int, Process] = {}
        self._pid_counter = 0
        self._events: dict[int, asyncio.Event] = {}
        self._waiters: dict[int, int] = {}
        self._shutdown = asyncio.Event()
        self._start_time = time.monotonic()

    def spawn(
        self,
        task_type: str,
        payload: dict,
        handler: Callable[..., Coroutine] | None = None,
        parent_pid: int | None = None,
        preemptible: bool = True,
    ) -> int:
        self._pid_counter += 1
        pid = self._pid_counter
        process = Process(pid, task_type, payload, handler=handler, parent_pid=parent_pid)
        self.process_table[pid] = process
        if parent_pid is not None:
            parent = self.process_table.get(parent_pid)
            if parent:
                parent.pcb.children.append(pid)
        self.scheduler.admit(process)
        if not preemptible:
            process.pcb.time_slice = float("inf")
        return pid

    async def run(self) -> None:
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
        self._shutdown.set()
        for core in self.cores:
            core.stop()
        await asyncio.gather(*core_tasks, return_exceptions=True)
        return self.process_table[pid].pcb.result

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
        self._get_event(process.pid).set()
        waiter_pid = self._waiters.pop(process.pid, None)
        if waiter_pid is not None:
            waiter = self.process_table.get(waiter_pid)
            if waiter and waiter.state == ProcessState.BLOCKED:
                waiter.pcb.context["wait_result"] = result
                self.scheduler.unblock(waiter)

    def io_complete(self, process: Process, result: Any = None) -> None:
        if process.state != ProcessState.BLOCKED:
            return
        process.pcb.context["io_result"] = result
        self.scheduler.unblock(process)

    def shutdown(self) -> None:
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
