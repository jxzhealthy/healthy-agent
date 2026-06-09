# Healthy Agent

[![CI](https://github.com/jxzhealthy/healthy-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jxzhealthy/healthy-agent/actions)
[![PyPI](https://img.shields.io/pypi/v/healthy-agent)](https://pypi.org/project/healthy-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**CPU-scheduling-inspired OS kernel for LLM agent workloads.**

Traditional agent frameworks use serial ReAct loops. Healthy Agent treats LLM API quota as CPU time and agent tasks as processes — with preemptive scheduling, multi-core concurrency, process forking, and IPC.

## Concepts

```
┌──────────────────┬──────────────────────────────┐
│  OS Concept      │  Healthy Agent Equivalent      │
├──────────────────┼──────────────────────────────┤
│  CPU Core        │  Worker slot (concurrent cap)│
│  Process         │  Agent task                  │
│  Fork            │  Spawn child tasks           │
│  Time Slice      │  Max execution before preempt│
│  MLFQ            │  Priority scheduling         │
│  Block/Wait      │  Waiting for LLM I/O         │
│  Device Driver   │  LLM / Tool provider         │
│  IPC Channel     │  Inter-agent messaging       │
│  System Call     │  fork / wait / exit / io     │
└──────────────────┴──────────────────────────────┘
```

## Install

```bash
pip install healthy-agent
# or
uv add healthy-agent
```

## Quick Start

### CLI

```bash
# Run a task with mock driver
healthy_agent run "Summarize this document" --cores 4 -v

# Run with Anthropic driver
healthy_agent run "Write a function" --driver anthropic --cores 4
```

### Python API

```python
import asyncio
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import fork

async def my_agent(process, kernel):
    # Fork child tasks (run in parallel on other cores)
    child_pid = await fork(kernel, process, "subtask", {"data": "..."}, handler=worker)
    # Wait for child (this process yields the core)
    await kernel._get_event(child_pid).wait()
    return kernel.process_table[child_pid].pcb.result

async def worker(process, kernel):
    # Do work (LLM call, tool use, etc.)
    return "result"

async def main():
    kernel = Kernel(num_cores=4)
    pid = kernel.spawn("agent", {}, handler=my_agent, preemptible=False)
    result = await kernel.exec(pid)
    print(result)

asyncio.run(main())
```

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                    User Space                         │
│  code_gen_agent | chat_agent | rag_agent | ...       │
├───────────────────────────────────────────────────────┤
│                  System Calls                         │
│  fork() | wait() | exit() | io()                     │
├───────────────────────────────────────────────────────┤
│                    Kernel                             │
│  ┌─────────────┐  ┌────────────────┐  ┌───────────┐ │
│  │  Scheduler  │  │   Core Pool    │  │  Process  │ │
│  │  (MLFQ)     │  │  (N workers)   │  │  Table    │ │
│  └─────────────┘  └────────────────┘  └───────────┘ │
├───────────────────────────────────────────────────────┤
│                    Drivers                            │
│  AnthropicDriver | ShellDriver | HttpDriver | ...    │
├───────────────────────────────────────────────────────┤
│                      IPC                             │
│  Channel (async message passing between processes)   │
└───────────────────────────────────────────────────────┘
```

## MLFQ Scheduling

- **Queue 0** (high priority, 0.5s slice): New tasks, just-unblocked I/O tasks
- **Queue 1** (medium, 2s slice): Demoted from Q0
- **Queue 2** (low, 10s slice): Long-running batch tasks
- **Queue 3** (background, no limit): Non-preemptible coordinators

Periodic boost every 30s prevents starvation.

## Project Structure

```
src/healthy_agent/
├── kernel/
│   ├── process.py      # Process + PCB + state machine
│   ├── scheduler.py    # MLFQ scheduler
│   ├── core.py         # Core (worker that executes processes)
│   └── runtime.py      # Kernel (orchestrator)
├── syscall/
│   └── api.py          # fork / wait / exit / io
├── drivers/
│   ├── base.py         # Driver ABC (LLMDriver, ToolDriver)
│   ├── anthropic.py    # Anthropic LLM driver
│   └── tool_builtin.py # Shell + HTTP tool drivers
├── ipc/
│   └── channel.py      # Async message channel
└── cli.py              # CLI entry point
```

## License

MIT
