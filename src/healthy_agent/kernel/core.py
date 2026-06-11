from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .process import Process, BlockedError

logger = logging.getLogger("healthy_agent.core")

if TYPE_CHECKING:
    from .runtime import Kernel


class Core:
    def __init__(self, core_id: int, kernel: Kernel):
        self.core_id = core_id
        self._kernel = kernel
        self.current: Process | None = None
        self._running = False
        self.total_executed = 0

    @property
    def idle(self) -> bool:
        return self.current is None

    async def run_loop(self) -> None:
        self._running = True
        while self._running:
            process = self._kernel.scheduler.schedule()
            if process is None:
                if self._kernel._shutdown.is_set():
                    break
                # Wait for work signal instead of polling
                self._kernel._work_available.clear()
                try:
                    await asyncio.wait_for(
                        self._kernel._work_available.wait(), timeout=0.05
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            self.current = process
            exec_start = time.monotonic()
            logger.debug("core=%d dispatch pid=%d type=%s pri=%d", self.core_id, process.pid, process.task_type, process.pcb.priority)

            try:
                ts = process.pcb.time_slice
                if ts == float("inf"):
                    result = await process.execute(self._kernel)
                else:
                    result = await asyncio.wait_for(
                        process.execute(self._kernel), timeout=ts
                    )
                process.pcb.cpu_time += time.monotonic() - exec_start
                self._kernel._complete(process, result)
                self.total_executed += 1

            except asyncio.TimeoutError:
                process.pcb.cpu_time += time.monotonic() - exec_start
                logger.debug("core=%d preempt pid=%d (time slice expired)", self.core_id, process.pid)
                self._kernel.scheduler.preempt(process)

            except BlockedError:
                process.pcb.cpu_time += time.monotonic() - exec_start

            except Exception as e:
                process.pcb.cpu_time += time.monotonic() - exec_start
                logger.error("core=%d pid=%d exception: %s", self.core_id, process.pid, e)
                self._kernel._complete(process, e)
                self.total_executed += 1

            finally:
                self.current = None

    def stop(self) -> None:
        self._running = False
