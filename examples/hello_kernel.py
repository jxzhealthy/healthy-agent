"""
Example 1: Hello Kernel - the simplest possible demo.

Demonstrates:
  - Kernel creation with multiple cores
  - Spawning processes with fork/wait syscalls
  - Parent-child process tree
  - MLFQ scheduling in action
"""
import asyncio
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait


async def greet_worker(process, kernel):
    """Child: returns a greeting after a brief pause."""
    name = process.payload["name"]
    await asyncio.sleep(0.05)
    return f"Hello, {name}!"


async def sum_worker(process, kernel):
    """Child: computes sum of 1..n."""
    n = process.payload["n"]
    await asyncio.sleep(0.05)
    return sum(range(1, n + 1))


async def coordinator(process, kernel):
    """Parent: forks two children in parallel, waits for both."""
    child_greet = await fork(kernel, process, "greet", {"name": "World"}, handler=greet_worker)
    child_sum = await fork(kernel, process, "sum", {"n": 100}, handler=sum_worker)

    greeting = await wait(kernel, process, child_greet)
    total = await wait(kernel, process, child_sum)

    return {"greeting": greeting, "sum": total}


async def main():
    kernel = Kernel(num_cores=2)

    pid = kernel.spawn("coordinator", {}, handler=coordinator, preemptible=False)
    result = await kernel.exec(pid)

    print(f"Result: {result}")
    print("\nProcess table:")
    for row in kernel.ps():
        print(f"  pid={row['pid']}  type={row['type']:12s}  state={row['state']}")


if __name__ == "__main__":
    asyncio.run(main())
