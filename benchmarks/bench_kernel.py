"""Performance benchmarks for Healthy Agent Kernel.

Run:
    python benchmarks/bench_kernel.py

Measures:
  - Spawn throughput (tasks/sec)
  - Scheduling latency (p50/p95/p99)
  - Concurrent execution throughput (multi-core)
  - Context switch overhead
  - Process lifecycle (spawn to complete)
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.kernel.process import ProcessState


async def run_until_done(kernel: Kernel, poll_interval: float = 0.01):
    """Run kernel and auto-shutdown when all tasks are terminated."""
    kernel._shutdown.clear()
    core_tasks = [asyncio.create_task(c.run_loop()) for c in kernel.cores]

    while True:
        await asyncio.sleep(poll_interval)
        active = sum(
            1 for p in kernel.process_table.values()
            if p.state != ProcessState.TERMINATED
        )
        if active == 0 and len(kernel.process_table) > 0:
            break

    kernel.shutdown()
    for c in kernel.cores:
        c.stop()
    await asyncio.gather(*core_tasks, return_exceptions=True)


def fmt_duration(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f} ?s"
    if seconds < 1:
        return f"{seconds * 1_000:.2f} ms"
    return f"{seconds:.3f} s"


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(label: str, value: str):
    print(f"  {label:<35} {value:>20}")


# --- Benchmark 1: Spawn Throughput --- ---
async def bench_spawn_throughput(num_tasks: int = 10_000) -> dict:
    """Measure how many tasks can be spawned per second."""
    kernel = Kernel(num_cores=1, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))

    async def noop_handler(process, k):
        return "done"

    start = time.perf_counter()
    for i in range(num_tasks):
        kernel.spawn("bench", {"i": i}, handler=noop_handler)
    elapsed = time.perf_counter() - start

    kernel.shutdown()
    throughput = num_tasks / elapsed

    print_header(f"Spawn Throughput ({num_tasks:,} tasks)")
    print_result("Total time", fmt_duration(elapsed))
    print_result("Throughput", f"{throughput:,.0f} spawns/sec")
    print_result("Per spawn", fmt_duration(elapsed / num_tasks))

    return {"throughput": throughput, "elapsed": elapsed}


# --- Benchmark 2: Scheduling Latency ---
async def bench_scheduling_latency(num_tasks: int = 1_000) -> dict:
    """Measure time from spawn to first execution."""
    kernel = Kernel(num_cores=4, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))
    latencies: list[float] = []

    async def measure_handler(process, k):
        latency = time.perf_counter() - process.payload["spawn_time"]
        latencies.append(latency)
        return "done"

    for i in range(num_tasks):
        kernel.spawn("bench", {"i": i, "spawn_time": time.perf_counter()}, handler=measure_handler)

    await run_until_done(kernel)

    print_header(f"Scheduling Latency ({num_tasks:,} tasks, 4 cores)")
    print_result("p50", fmt_duration(percentile(latencies, 50)))
    print_result("p95", fmt_duration(percentile(latencies, 95)))
    print_result("p99", fmt_duration(percentile(latencies, 99)))
    print_result("Mean", fmt_duration(statistics.mean(latencies)))
    print_result("Std dev", fmt_duration(statistics.stdev(latencies) if len(latencies) > 1 else 0))

    return {
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "mean": statistics.mean(latencies),
    }


# --- Benchmark 3: Concurrent Throughput ---
async def bench_concurrent_throughput(num_tasks: int = 2_000) -> dict:
    """Measure end-to-end throughput with varying core counts."""
    results = {}

    for num_cores in [1, 2, 4, 8]:
        kernel = Kernel(num_cores=num_cores, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))

        async def cpu_work(process, k):
            total = 0
            for j in range(1000):
                total += j * j
            return total

        start = time.perf_counter()
        for i in range(num_tasks):
            kernel.spawn("cpu", {"i": i}, handler=cpu_work)
        await run_until_done(kernel)
        elapsed = time.perf_counter() - start

        throughput = num_tasks / elapsed
        results[num_cores] = {"throughput": throughput, "elapsed": elapsed}

    print_header(f"Concurrent Throughput ({num_tasks:,} tasks)")
    for cores, data in results.items():
        print_result(f"{cores} core(s)", f"{data['throughput']:,.0f} tasks/sec ({fmt_duration(data['elapsed'])})")

    baseline = results[1]["throughput"]
    for cores in [2, 4, 8]:
        speedup = results[cores]["throughput"] / baseline
        print_result(f"  Speedup ({cores} vs 1)", f"{speedup:.2f}x")

    return results


# --- Benchmark 4: IO-Bound Tasks ---
async def bench_io_bound(num_tasks: int = 500) -> dict:
    """Measure throughput with simulated IO-bound tasks (async sleep)."""
    results = {}

    for num_cores in [1, 4, 8]:
        kernel = Kernel(num_cores=num_cores, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))

        async def io_task(process, k):
            await asyncio.sleep(0.001)  # Simulate 1ms IO
            return "done"

        start = time.perf_counter()
        for i in range(num_tasks):
            kernel.spawn("io", {"i": i}, handler=io_task)
        await run_until_done(kernel)
        elapsed = time.perf_counter() - start

        throughput = num_tasks / elapsed
        results[num_cores] = {"throughput": throughput, "elapsed": elapsed}

    print_header(f"IO-Bound Throughput ({num_tasks:,} tasks, 1ms sleep each)")
    for cores, data in results.items():
        print_result(f"{cores} core(s)", f"{data['throughput']:,.0f} tasks/sec ({fmt_duration(data['elapsed'])})")

    return results


# --- Benchmark 5: Process Lifecycle ---
async def bench_lifecycle(num_tasks: int = 1_000) -> dict:
    """Measure full lifecycle: spawn  ->  schedule  ->  execute  ->  complete."""
    kernel = Kernel(num_cores=4, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))
    lifecycles: list[float] = []
    spawn_times: dict[int, float] = {}

    async def lifecycle_handler(process, k):
        return "done"

    start = time.perf_counter()
    for i in range(num_tasks):
        t = time.perf_counter()
        pid = kernel.spawn("lifecycle", {"i": i}, handler=lifecycle_handler)
        spawn_times[pid] = t

    # Run and collect completion times
    original_complete = kernel._complete

    def timed_complete(process, result):
        if process.pid in spawn_times:
            lifecycles.append(time.perf_counter() - spawn_times[process.pid])
        original_complete(process, result)

    kernel._complete = timed_complete
    await run_until_done(kernel)
    total_elapsed = time.perf_counter() - start

    print_header(f"Process Lifecycle ({num_tasks:,} tasks, 4 cores)")
    print_result("Total time", fmt_duration(total_elapsed))
    print_result("Throughput", f"{num_tasks / total_elapsed:,.0f} tasks/sec")
    print_result("Lifecycle p50", fmt_duration(percentile(lifecycles, 50)))
    print_result("Lifecycle p95", fmt_duration(percentile(lifecycles, 95)))
    print_result("Lifecycle p99", fmt_duration(percentile(lifecycles, 99)))

    return {
        "total": total_elapsed,
        "p50": percentile(lifecycles, 50),
        "p95": percentile(lifecycles, 95),
        "p99": percentile(lifecycles, 99),
    }


# --- Benchmark 6: Memory / Reap ---
async def bench_reap(num_tasks: int = 5_000) -> dict:
    """Measure reap performance after many terminated processes."""
    kernel = Kernel(num_cores=4, max_processes=num_tasks + 100, max_spawn_rate=float("inf"))
    kernel._reap_ttl = 0.0  # Immediate reap eligibility

    async def quick_handler(process, k):
        return "done"

    for i in range(num_tasks):
        kernel.spawn("reap", {"i": i}, handler=quick_handler)
    await run_until_done(kernel)

    # Now reap all terminated processes
    start = time.perf_counter()
    reaped = kernel.reap()
    elapsed = time.perf_counter() - start

    print_header(f"Reap Performance ({num_tasks:,} terminated processes)")
    print_result("Reaped", f"{reaped:,} processes")
    print_result("Reap time", fmt_duration(elapsed))
    print_result("Per process", fmt_duration(elapsed / max(reaped, 1)))

    return {"reaped": reaped, "elapsed": elapsed}


# --- Main ---
async def main():
    print("\n" + "=" * 60)
    print("  Healthy Agent Kernel  ->  Performance Benchmarks")
    print("=" * 60)
    print(f"  Python {sys.version.split()[0]} | PID {os.getpid()}")

    await bench_spawn_throughput()
    await bench_scheduling_latency()
    await bench_concurrent_throughput()
    await bench_io_bound()
    await bench_lifecycle()
    await bench_reap()

    print(f"\n{'=' * 60}")
    print("  All benchmarks complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
