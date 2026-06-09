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
| Namespace | Session (isolated memory + history) |
| Supervisor | Auto-retry with error correction |

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
from healthy_agent.syscall import io
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

# With DeepSeek / Qwen / Ollama / Zhipu / OpenAI
healthy-agent run "Explain async" --driver deepseek
healthy-agent run "解释量子计算" --driver qwen
```

### Web Server + WebSocket

```bash
# Start the server with a real LLM driver
healthy-agent serve --driver anthropic --cores 4

# Or with other providers
healthy-agent serve --driver deepseek --model deepseek-chat
healthy-agent serve --driver ollama --model llama3
```

Open `http://localhost:8000` for the built-in debug UI, or connect via WebSocket:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/my-session");
ws.send(JSON.stringify({ prompt: "Hello!", mode: "agent" }));
// Receives: thinking → stream chunks → tool_call events → done
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      User Space                              │
│  Executor │ Workflow │ MultiAgent │ RAG │ Reflexion          │
├──────────────────────────────────────────────────────────────┤
│                       System Calls                           │
│  fork() │ wait() │ exit() │ io() │ supervised_fork()         │
├──────────────────────────────────────────────────────────────┤
│                         Kernel                               │
│  ┌───────────┐ ┌────────────┐ ┌─────────────┐ ┌──────────┐ │
│  │ Scheduler │ │ Core Pool  │ │   Process   │ │ Session  │ │
│  │ (MLFQ)    │ │ (N cores)  │ │   Table     │ │ Manager  │ │
│  └───────────┘ └────────────┘ └─────────────┘ └──────────┘ │
├──────────────────────────────────────────────────────────────┤
│                        Drivers                               │
│  Anthropic │ OpenAI │ DeepSeek │ Zhipu │ Qwen │ Ollama      │
├──────────────────────────────────────────────────────────────┤
│                    Skills & Tools                            │
│  file_tools │ shell_tools │ python_eval │ LLM skills         │
├──────────────────────────────────────────────────────────────┤
│          Memory          │           IPC / MCP               │
│  Short-term │ Long-term  │  Channel │ McpServer │ McpClient  │
│  (RAM/TTL)  │ (Disk/     │  (async  │ (JSON-RPC │ (connect   │
│             │  Redis/Mem0)│  msgs)   │  stdio)   │  external)│
└──────────────────────────────────────────────────────────────┘
```

## Agent Patterns

### Executor (Task Execution Engine)

The `Executor` is the low-level execution engine that handles LLM generation and tool invocation. Strategies like `ReflexionAgent` sit above it and decide when/how to retry.

```python
from healthy_agent.agent import Executor
from healthy_agent.skill import SkillRegistry

skills = SkillRegistry()
skills.load_directory("./skills")

executor = Executor(driver, skills, max_rounds=10)
result = await executor.run("Read config.yaml and fix the syntax error")
# LLM autonomously: read_file → analyze → edit_file → done
```

### DAG Workflow

Define steps with dependencies. Independent steps run in parallel on different cores.

```python
from healthy_agent.agent import Workflow

wf = Workflow(kernel)
wf.add("fetch", fetch_handler)
wf.add("parse", parse_handler, depends_on=["fetch"])
wf.add("analyze", analyze_handler, depends_on=["fetch"])
wf.add("report", report_handler, depends_on=["parse", "analyze"])
result = await wf.execute(parent_process)
# fetch runs first, then parse+analyze in parallel, then report
```

### Multi-Agent Coordination

Three patterns for orchestrating multiple agents:

```python
from healthy_agent.agent import MultiAgentCoordinator, AgentConfig

coordinator = MultiAgentCoordinator(kernel)

# Parallel — all agents run concurrently
result = await coordinator.parallel(agents, parent)

# Pipeline — output feeds into next agent
result = await coordinator.pipeline(agents, parent, initial_input="start")

# Debate — agents discuss a topic over multiple rounds
result = await coordinator.debate(agents, parent, topic="Best approach?", rounds=3)
```

### Supervisor (Auto-Retry)

Fork a child process with automatic retry and error correction — like a supervisor that restarts crashed processes, but feeds error context back into the next attempt.

```python
from healthy_agent.syscall import supervised_fork

result = await supervised_fork(
    kernel, parent, "generate_code", payload,
    handler=code_handler,
    max_retries=3,
    judge=judge_fn,  # async (result, payload) → (passed, feedback)
)
```

### RAG (Retrieval-Augmented Generation)

Built-in keyword-based vector store for context retrieval. Swap with chromadb/pinecone for production.

```python
from healthy_agent.agent import RAGMixin

rag = RAGMixin()
rag.ingest("Healthy Agent uses MLFQ scheduling")
rag.ingest("Processes have 5 states: new, ready, running, blocked, terminated")

context = rag.retrieve_context("How does scheduling work?")
# Pass context into Executor or driver.generate()
```

## LLM Drivers

| Driver | Provider | Env Var | Default Model |
|--------|----------|---------|---------------|
| `AnthropicDriver` | Anthropic Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| `OpenAIDriver` | OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| `DeepSeekDriver` | DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `ZhipuDriver` | Zhipu (GLM) | `ZHIPU_API_KEY` | `glm-4` |
| `QwenDriver` | Qwen (DashScope) | `DASHSCOPE_API_KEY` | `qwen-plus` |
| `OllamaDriver` | Ollama (local) | — | `llama3` |

All OpenAI-compatible drivers support streaming via `driver.stream()`.

## Skills & Tools

Two-layer capability system:

- **Tool** — pure execution, no LLM needed. Input → execute → output.
- **Skill** — extends Tool with LLM access for intelligent processing.

Built-in tools (loaded from `skills/`):

| Tool | Description |
|------|-------------|
| `read_file` | Read file content |
| `write_file` | Write content to file |
| `edit_file` | Find-and-replace in file |
| `shell` | Execute shell commands |
| `http_request` | HTTP GET/POST |
| `python_eval` | Run Python code in subprocess |
| `list_dir` | List directory contents |
| `search_text` | Grep-like text/regex search |

Built-in LLM skills: `summarize`, `code_gen`, `web_search`

Custom skills are loaded from any directory via `SkillRegistry.load_directory()`.

## Memory System

Two-tier memory inspired by RAM + Disk:

- **Short-term** — in-process, per-session, auto-expires (default 5min TTL)
- **Long-term** — persisted to disk (JSON), survives restarts

Pluggable backends for distributed use cases:

| Backend | Storage | Use Case |
|---------|---------|----------|
| `local` (default) | JSON file | Single-node, development |
| `redis` | Redis | Multi-node, shared state |
| `mem0` | Mem0 AI memory | Intelligent long-term memory |

```python
# Via SessionManager
sessions = SessionManager(memory_backend="redis", redis_url="redis://localhost:6379")
session = sessions.create(metadata={"user": "alice"})
session.mem.remember("preference", "dark_mode", persist=True)
value = session.mem.recall("preference")
```

## Sessions

Each session is an isolated execution context — like a Linux namespace. Own memory, own message history, no cross-session leakage.

```python
sessions = SessionManager()
session = sessions.create(metadata={"user": "alice"})
session.add_message("user", "What is MLFQ?")
# Messages and memory are scoped to this session
```

## MCP (Model Context Protocol)

Expose or consume agent capabilities over the MCP JSON-RPC protocol.

**Server** — expose tools to external MCP clients:

```python
from healthy_agent.mcp import McpServer

server = McpServer()
server.register_tool("greet", "Say hello", {"type": "object", "properties": {...}}, handler)
```

**Client** — connect to external MCP servers via subprocess stdio:

```python
from healthy_agent.mcp import McpClient

client = McpClient()
await client.connect(["python", "-m", "some_mcp_server"])
await client.initialize()
tools = await client.list_tools()
result = await client.call_tool("some_tool", {"arg": "value"})
```

## MLFQ Scheduling

```
Queue 0  ██████████  High priority   (0.5s slice)   ← new tasks, unblocked I/O
Queue 1  ██████      Medium          (2s slice)      ← demoted from Q0
Queue 2  ████        Low             (10s slice)     ← long-running batch
Queue 3  ██          Background      (no limit)      ← non-preemptible

         ↑ Periodic boost every 30s (anti-starvation)
```

Processes enter at Queue 0. If they use their full time slice (CPU-bound), they are demoted. I/O-bound processes that block early retain their priority. A periodic boost prevents starvation.

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create a session |
| `GET` | `/sessions` | List sessions |
| `POST` | `/sessions/{id}/tasks` | Submit a task |
| `GET` | `/sessions/{id}/tasks/{tid}` | Get task result |
| `POST` | `/sessions/{id}/memory` | Store memory |
| `GET` | `/sessions/{id}/memory/{key}` | Recall memory |
| `GET` | `/sessions/{id}/messages` | Get message history |
| `GET` | `/skills` | List available skills |
| `POST` | `/sessions/{id}/skills/{name}` | Invoke a skill |
| `GET` | `/kernel/ps` | Process table |
| `GET` | `/kernel/stats` | Scheduler stats |
| `WS` | `/ws/{session_id}` | WebSocket chat (streaming + agent mode) |

### WebSocket Messages

Client sends:
```json
{"prompt": "your message", "mode": "agent"}
```

Server sends (keyed by `msg_id` for concurrent messages):
- `{"type": "thinking", "msg_id": "..."}` — processing started
- `{"type": "stream", "content": "...", "msg_id": "..."}` — streaming chunk
- `{"type": "tool_call", "name": "...", "input": {...}, "result": "...", "msg_id": "..."}` — tool invocation
- `{"type": "done", "content": "full text", "msg_id": "..."}` — complete response
- `{"type": "error", "content": "...", "msg_id": "..."}` — error occurred

## Project Structure

```
src/
├── healthy_agent/
│   ├── kernel/
│   │   ├── process.py      # Process + PCB + state machine
│   │   ├── scheduler.py    # MLFQ scheduler
│   │   ├── core.py         # Core (worker executing processes)
│   │   └── runtime.py      # Kernel (orchestrator)
│   ├── syscall/
│   │   ├── api.py          # fork / wait / exit / io
│   │   └── supervisor.py   # supervised_fork (auto-retry)
│   ├── agent/
│   │   ├── executor.py     # Executor (task execution engine)
│   │   ├── workflow.py     # DAG workflow engine
│   │   ├── multi.py        # Multi-agent coordinator
│   │   └── rag.py          # RAG (vector store + retrieval)
│   ├── drivers/
│   │   ├── base.py         # LLMDriver / ToolDriver ABC
│   │   ├── anthropic.py    # Anthropic Claude driver
│   │   ├── openai_compat.py # OpenAI / DeepSeek / Zhipu / Qwen / Ollama
│   │   └── tool_builtin.py # Shell + HTTP drivers
│   ├── skill/
│   │   ├── base.py         # Tool / Skill base classes
│   │   ├── builtin.py      # Built-in tools and skills
│   │   └── registry.py     # SkillRegistry (load, route, invoke)
│   ├── memory/
│   │   ├── store.py        # ShortTermMemory / LongTermMemory / MemoryManager
│   │   └── backend.py      # Redis / Mem0 backends
│   ├── session/
│   │   └── manager.py      # Session + SessionManager
│   ├── mcp/
│   │   ├── protocol.py     # MCP JSON-RPC protocol
│   │   ├── server.py       # McpServer
│   │   └── client.py       # McpClient
│   └── ipc/
│       └── channel.py      # Async message channel
├── api/
│   ├── app.py              # FastAPI app + REST + WebSocket
│   └── web.py              # Built-in debug web UI
└── cli.py                  # CLI (run / serve / ps)
skills/
├── file_tools.py           # read_file, write_file, edit_file, list_dir, search_text
└── shell_tools.py          # shell, http_request, python_eval
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
