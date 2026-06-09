# Healthy Agent

[![CI](https://github.com/jxzhealthy/healthy-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jxzhealthy/healthy-agent/actions)
[![PyPI](https://img.shields.io/pypi/v/healthy-agent)](https://pypi.org/project/healthy-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**A CPU-scheduling-inspired runtime kernel for LLM agent workloads.**

[English](#english) | [中文](#中文)

---

<a id="english"></a>

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
    # Simulate I/O
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

---

<a id="中文"></a>

# Healthy Agent

**基于 CPU 调度模型的 LLM Agent 运行时内核。**

## 为什么做这个？

传统 Agent 框架用串行 ReAct 循环 —— 思考、执行、观察、再思考。这相当于在 2025 年跑单线程操作系统。

Healthy Agent 把 Agent 执行重新定义为**操作系统问题**：

- **LLM API 配额 = CPU 时间** —— 稀缺资源，需要调度
- **Agent 任务 = 进程** —— 有生命周期、优先级、状态
- **多个并发请求 = 多核** —— 真正的并行
- **等待 API 响应 = I/O 阻塞** —— 不要浪费核心空等

```
ReAct（单线程）：     思考 → 执行 → 观察 → 思考 → 执行 → ...

Healthy Agent（多核）：核心0: [任务A] ──LLM调用──▶ [阻塞] ──▶ [恢复]
                      核心1: [任务B] ──工具调用──▶ [阻塞] ──▶ [恢复]
                      核心2: [任务C] ──运行中──▶ [完成]
                      核心3: [任务D] ──运行中──▶ [抢占] ──▶ [恢复]
```

## 核心概念

| 操作系统概念 | Healthy Agent 对应 |
|-------------|-------------------|
| CPU 核心 | Worker 槽位（并发执行容量） |
| 进程 | Agent 任务（含 PCB、状态、优先级） |
| Fork | 派生子任务，并行执行 |
| 时间片 | 最大执行时间，超时抢占 |
| MLFQ | 多级反馈队列调度 |
| 阻塞 | 等待 LLM API / 工具 I/O |
| 设备驱动 | LLM 提供者 / 工具提供者 |
| IPC | Agent 间异步消息通道 |
| 系统调用 | `fork()` / `wait()` / `exit()` / `io()` |

## 安装

```bash
pip install healthy-agent
# 或
uv add healthy-agent
```

## 快速开始

```python
import asyncio
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import fork, wait

async def 协调者(process, kernel):
    # fork 子任务 —— 在其他核心上并行运行
    子任务1 = await fork(kernel, process, "获取数据", {"url": "..."}, handler=获取)
    子任务2 = await fork(kernel, process, "计算", {"x": 42}, handler=计算)

    # wait 等待结果 —— 当前核心释放给其他任务
    数据 = await wait(kernel, process, 子任务1)
    结果 = await wait(kernel, process, 子任务2)
    return {"数据": 数据, "结果": 结果}

async def 获取(process, kernel):
    await asyncio.sleep(0.1)  # 模拟 I/O
    return "已获取"

async def 计算(process, kernel):
    return process.payload["x"] ** 2

async def main():
    kernel = Kernel(num_cores=4)  # 4 核
    pid = kernel.spawn("协调者", {}, handler=协调者, preemptible=False)
    result = await kernel.exec(pid)
    print(result)  # {'数据': '已获取', '结果': 1764}

asyncio.run(main())
```

## MLFQ 调度

```
队列0  ██████████  最高优先级  (0.5s 时间片)  ← 新任务、刚从阻塞恢复的任务
队列1  ██████      中优先级    (2s 时间片)    ← 从队列0降级
队列2  ████        低优先级    (10s 时间片)   ← 长时间运行的批量任务
队列3  ██          后台        (无限制)       ← 不可抢占的协调者

         ↑ 每 30s 全局提升（防饥饿）
```

## 架构

```
┌─────────────────────────────────────────────────┐
│             用户空间（Agent 程序）                 │
│  协调者 | 数据获取 | 分析器 | ...                  │
├─────────────────────────────────────────────────┤
│                  系统调用                         │
│  fork() │ wait() │ exit() │ io()                │
├─────────────────────────────────────────────────┤
│                   内核                           │
│  ┌───────────┐ ┌────────────┐ ┌─────────────┐  │
│  │  调度器   │ │  核心池     │ │  进程表      │  │
│  │ (MLFQ)    │ │ (N 核心)   │ │             │  │
│  └───────────┘ └────────────┘ └─────────────┘  │
├─────────────────────────────────────────────────┤
│                  驱动层                          │
│  Anthropic │ Shell │ HTTP │ (自定义驱动)         │
├─────────────────────────────────────────────────┤
│                   IPC                           │
│  Channel（异步消息传递）                          │
└─────────────────────────────────────────────────┘
```

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT
