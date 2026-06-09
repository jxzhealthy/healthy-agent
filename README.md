# Healthy Agent

[![CI](https://github.com/jxzhealthy/healthy-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jxzhealthy/healthy-agent/actions)
[![PyPI](https://img.shields.io/pypi/v/healthy-agent)](https://pypi.org/project/healthy-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**A CPU-scheduling-inspired runtime kernel for LLM agent workloads.**

[English](README.md) | [中文](README_CN.md)

## Why Healthy Agent?

Traditional agent frameworks run tasks in a serial ReAct loop — think, act, observe, repeat. This is like running a single-threaded OS in 2025.

Healthy Agent reimagines agent execution as an **operating system problem**:

- **LLM API quota = CPU time** — a scarce resource that must be scheduled
- **Agent tasks = processes** — with lifecycle, priority, and state
- **Multiple concurrent requests = multi-core** — true parallelism
- **Long I/O waits = blocking** — don't waste cores waiting for API responses

```
ReAct (single-threaded):     Think → Act → Observe → Think → Act → ...

Healthy Agent (multi-core):  Core 0: [Task A] ──LLM call──▶ [blocked] ──▶ [resume]
                             Core 1: [Task B] ──tool call──▶ [blocked] ──▶ [resume]
                             Core 2: [Task C] ──running──▶ [done]
                             Core 3: [Task D] ──running──▶ [preempted] ──▶ [resume]
```

## Concepts

| OS Concept | Healthy Agent Equivalent |
|------------|--------------------------|
| CPU Core | Worker slot (concurrent execution capacity) |
| Process | Agent task (with PCB, state, priority) |
| Fork | Spawn child tasks for parallel work |
| Time Slice | Max execution time before preemption |
| MLFQ | Multi-Level Feedback Queue scheduling |
| Blocked | Waiting for LLM API / tool I/O |
| Device Driver | LLM provider / Tool provider |
| IPC | Async message channel between agents |
| System Call | `fork()` / `wait()` / `exit()` / `io()` |

## Install

```bash
pip install healthy-agent
# or
uv add healthy-agent
```

## Quick Start

### Python API

```python
import asyncio
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import fork, wait

async def coordinator(process, kernel):
    # Fork child tasks — they run in parallel on other cores
    child1 = await fork(kernel, process, "fetch", {"url": "..."}, handler=fetch_data)
    child2 = await fork(kernel, process, "compute", {"x": 42}, handler=compute)

    # Wait for results — this core is freed for other tasks
    data = await wait(kernel, process, child1)
    result = await wait(kernel, process, child2)
    return {"data": data, "result": result}

async def fetch_data(process, kernel):
    await asyncio.sleep(0.1)
    return "fetched"

async def compute(process, kernel):
    return process.payload["x"] ** 2

async def main():
    kernel = Kernel(num_cores=4)
    pid = kernel.spawn("coordinator", {}, handler=coordinator, preemptible=False)
    result = await kernel.exec(pid)
    print(result)  # {'data': 'fetched', 'result': 1764}

asyncio.run(main())
```

### With Real LLM Driver

```python
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import fork, wait, io
from healthy_agent.drivers.anthropic import AnthropicDriver

driver = AnthropicDriver(model="claude-sonnet-4-20250514")

async def agent(process, kernel):
    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": "What is 2+2?"}]
    ))
    return result.data["text"]
```

### CLI

```bash
# Run a task
healthy-agent run "Summarize this document" --cores 4 -v

# With Anthropic
healthy-agent run "Write a function" --driver anthropic --cores 4
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│              User Space (Agents)                │
│  coordinator | fetcher | analyzer | ...         │
├─────────────────────────────────────────────────┤
│                System Calls                     │
│  fork() │ wait() │ exit() │ io()                │
├─────────────────────────────────────────────────┤
│                  Kernel                         │
│  ┌───────────┐ ┌────────────┐ ┌─────────────┐  │
│  │ Scheduler │ │ Core Pool  │ │  Process    │  │
│  │ (MLFQ)    │ │ (N cores)  │ │  Table      │  │
│  └───────────┘ └────────────┘ └─────────────┘  │
├─────────────────────────────────────────────────┤
│                  Drivers                        │
│  Anthropic │ Shell │ HTTP │ (your driver)       │
├─────────────────────────────────────────────────┤
│                    IPC                          │
│  Channel (async message passing)                │
└─────────────────────────────────────────────────┘
```

## MLFQ Scheduling

```
Queue 0  ██████████  High priority   (0.5s slice)   ← new tasks, unblocked I/O
Queue 1  ██████      Medium          (2s slice)      ← demoted from Q0
Queue 2  ████        Low             (10s slice)     ← long-running batch
Queue 3  ██          Background      (no limit)      ← non-preemptible
                                                      
         ↑ Periodic boost every 30s (anti-starvation)
```

## Project Structure

```
src/healthy_agent/
├── kernel/
│   ├── process.py      # Process + PCB + state machine
│   ├── scheduler.py    # MLFQ scheduler
│   ├── core.py         # Core (worker executing processes)
│   └── runtime.py      # Kernel (orchestrator)
├── syscall/
│   └── api.py          # fork / wait / exit / io
├── drivers/
│   ├── base.py         # LLMDriver / ToolDriver ABC
│   ├── anthropic.py    # Anthropic Claude driver
│   └── tool_builtin.py # Shell + HTTP drivers
├── ipc/
│   └── channel.py      # Async message channel
└── cli.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
