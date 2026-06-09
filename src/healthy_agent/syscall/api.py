from __future__ import annotations

from typing import Any, Callable, Coroutine, TYPE_CHECKING

from ..kernel.process import Process

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel


async def fork(
    kernel: Kernel,
    parent: Process,
    task_type: str,
    payload: dict,
    handler: Callable[..., Coroutine] | None = None,
    preemptible: bool = True,
) -> int:
    return kernel.spawn(task_type, payload, handler=handler, parent_pid=parent.pid, preemptible=preemptible)


async def wait(kernel: Kernel, parent: Process, child_pid: int) -> Any:
    child = kernel.process_table.get(child_pid)
    if child is None:
        raise ValueError(f"No such process: {child_pid}")
    event = kernel._get_event(child_pid)
    await event.wait()
    return child.pcb.result


async def exit(kernel: Kernel, process: Process, result: Any = None) -> None:
    kernel._complete(process, result)


async def io(kernel: Kernel, process: Process, coro: Coroutine) -> Any:
    return await coro
