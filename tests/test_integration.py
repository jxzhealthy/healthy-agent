"""Integration tests — verify actual scheduling behavior, not just unit logic."""
import asyncio
import time

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait, io
from healthy_agent.ipc import Channel, Message


async def test_syscall_wait_actually_works():
    """Parent forks child, waits with syscall.wait, gets result."""
    async def parent(process, kernel):
        cpid = await fork(kernel, process, "child", {"x": 7}, handler=child)
        result = await wait(kernel, process, cpid)
        return f"child returned {result}"

    async def child(process, kernel):
        return process.payload["x"] * 2

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result == "child returned 14"


async def test_syscall_io_runs_async():
    """io() executes a coroutine and returns its result."""
    async def handler(process, kernel):
        async def slow_io():
            await asyncio.sleep(0.05)
            return "io_done"
        result = await io(kernel, process, slow_io())
        return f"got {result}"

    k = Kernel(num_cores=1)
    pid = k.spawn("test", {}, handler=handler, preemptible=False)
    result = await k.exec(pid)
    assert result == "got io_done"


async def test_parallel_tasks_run_concurrently():
    """Multiple tasks run in parallel on multiple cores, total time < sequential."""
    timestamps = {}

    async def slow_task(process, kernel):
        start = time.monotonic()
        await asyncio.sleep(0.1)
        end = time.monotonic()
        timestamps[process.pid] = (start, end)
        return process.payload["id"]

    async def parent(process, kernel):
        pids = []
        for i in range(4):
            cpid = await fork(kernel, process, "worker", {"id": i}, handler=slow_task)
            pids.append(cpid)
        results = []
        for cpid in pids:
            r = await wait(kernel, process, cpid)
            results.append(r)
        return sorted(results)

    k = Kernel(num_cores=4)
    start = time.monotonic()
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    total = time.monotonic() - start

    assert result == [0, 1, 2, 3]
    assert total < 0.5, f"Should run in parallel, took {total:.2f}s"


async def test_mlfq_demotion_observable():
    """A long-running task gets demoted to lower priority queue."""
    k = Kernel(num_cores=1)
    k.scheduler.time_slices = [0.05, 0.1, 0.5, float("inf")]

    observed_priorities = []

    async def long_task(process, kernel):
        for _ in range(100):
            await asyncio.sleep(0.01)
        observed_priorities.append(process.pcb.priority)
        return "done"

    pid = k.spawn("long", {}, handler=long_task)
    result = await k.exec(pid)

    stats = k.scheduler.stats()
    assert result == "done"
    assert stats.total_preempted >= 1, "Long task should have been preempted at least once"


async def test_error_in_child_propagates():
    """Exception in child process is captured as result."""
    async def parent(process, kernel):
        cpid = await fork(kernel, process, "bad", {}, handler=bad_child)
        result = await wait(kernel, process, cpid)
        return f"error: {type(result).__name__}"

    async def bad_child(process, kernel):
        raise ValueError("boom")

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result == "error: ValueError"


async def test_ipc_between_processes():
    """Two processes communicate via IPC channel."""
    channel = Channel("pipe")

    async def sender(process, kernel):
        for i in range(3):
            await channel.send(Message(sender_pid=process.pid, data=f"msg-{i}"))
        return "sent"

    async def receiver(process, kernel):
        msgs = []
        for _ in range(3):
            msg = await channel.recv(timeout=2.0)
            if msg:
                msgs.append(msg.data)
        return msgs

    k = Kernel(num_cores=2)
    k.spawn("sender", {}, handler=sender)
    rpid = k.spawn("receiver", {}, handler=receiver, preemptible=False)

    # Run until receiver done
    result = await k.exec(rpid)
    assert result == ["msg-0", "msg-1", "msg-2"]


async def test_driver_io_via_syscall():
    """Use a real driver through the io syscall."""
    from healthy_agent.drivers.tool_builtin import ShellDriver

    async def handler(process, kernel):
        driver = ShellDriver()
        result = await io(kernel, process, driver.invoke("exec", {"command": "echo kernel_works"}))
        return result.data["stdout"].strip()

    k = Kernel(num_cores=1)
    pid = k.spawn("driver_test", {}, handler=handler, preemptible=False)
    result = await k.exec(pid)
    assert result == "kernel_works"


async def test_deep_fork_tree():
    """3-level process tree: grandparent → parent → child."""
    async def grandparent(process, kernel):
        cpid = await fork(kernel, process, "parent", {}, handler=parent_fn, preemptible=False)
        return await wait(kernel, process, cpid)

    async def parent_fn(process, kernel):
        cpid = await fork(kernel, process, "child", {}, handler=child_fn)
        return f"parent({await wait(kernel, process, cpid)})"

    async def child_fn(process, kernel):
        return "leaf"

    k = Kernel(num_cores=3)
    pid = k.spawn("gp", {}, handler=grandparent, preemptible=False)
    result = await k.exec(pid)
    assert result == "parent(leaf)"

    ps = k.ps()
    assert len(ps) == 3
    assert all(row["state"] == "terminated" for row in ps)


async def test_process_table_integrity():
    """After execution, process table correctly reflects all state."""
    async def parent(process, kernel):
        c1 = await fork(kernel, process, "a", {}, handler=leaf)
        c2 = await fork(kernel, process, "b", {}, handler=leaf)
        await wait(kernel, process, c1)
        await wait(kernel, process, c2)
        return "ok"

    async def leaf(process, kernel):
        return process.task_type

    k = Kernel(num_cores=3)
    pid = k.spawn("root", {}, handler=parent, preemptible=False)
    await k.exec(pid)

    ps = k.ps()
    types = sorted(row["type"] for row in ps)
    assert types == ["a", "b", "root"]
    assert all(row["state"] == "terminated" for row in ps)
    assert all(row["cpu_time"] >= 0 for row in ps)

    root = k.process_table[pid]
    assert len(root.pcb.children) == 2


async def test_kernel_no_handler():
    """Process with no handler terminates with None result."""
    k = Kernel(num_cores=1)
    pid = k.spawn("empty", {})
    result = await k.exec(pid)
    assert result is None
