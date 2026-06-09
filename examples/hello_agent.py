"""
Example: A simple agent running on Healthy Agent kernel.

Demonstrates fork/wait syscalls and multi-core scheduling.
The parent agent forks two child tasks, waits for both, and combines results.
"""
import asyncio
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait


async def coordinator(process, kernel):
    """Parent: forks two workers, waits for results."""
    task = process.payload["task"]

    w1 = await fork(kernel, process, "greet", {"name": task}, handler=greet_worker)
    w2 = await fork(kernel, process, "count", {"n": 5}, handler=count_worker)

    greeting = await wait(kernel, process, w1)
    total = await wait(kernel, process, w2)

    return {"greeting": greeting, "sum": total}


async def greet_worker(process, kernel):
    """Child: returns a greeting."""
    name = process.payload["name"]
    await asyncio.sleep(0.05)
    return f"Hello, {name}!"


async def count_worker(process, kernel):
    """Child: sums 1..n."""
    n = process.payload["n"]
    await asyncio.sleep(0.05)
    return sum(range(1, n + 1))


async def main():
    kernel = Kernel(num_cores=2)

    pid = kernel.spawn("coordinator", {"task": "World"}, handler=coordinator, preemptible=False)
    result = await kernel.exec(pid)

    print(f"Result: {result}")
    print("\nProcess table:")
    for row in kernel.ps():
        print(f"  pid={row['pid']} type={row['type']} state={row['state']} cpu={row['cpu_time']}s")


if __name__ == "__main__":
    asyncio.run(main())
