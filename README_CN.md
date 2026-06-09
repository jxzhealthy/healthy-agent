# Healthy Agent

[![CI](https://github.com/jxzhealthy/healthy-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jxzhealthy/healthy-agent/actions)
[![PyPI](https://img.shields.io/pypi/v/healthy-agent)](https://pypi.org/project/healthy-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**基于 CPU 调度模型的 LLM Agent 运行时内核。**

[English](README.md) | [中文](README_CN.md)

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
| 命名空间 | Session（隔离的内存 + 历史） |
| 监控进程 | 自动重试 + 错误修正 |

## 安装

```bash
pip install healthy-agent
# 或
uv add healthy-agent
```

## 快速开始

### Python API

```python
import asyncio
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import fork, wait

async def coordinator(process, kernel):
    # fork 子任务 —— 在其他核心上并行运行
    child1 = await fork(kernel, process, "fetch", {"url": "..."}, handler=fetch_data)
    child2 = await fork(kernel, process, "compute", {"x": 42}, handler=compute)

    # wait 等待结果 —— 当前核心释放给其他任务
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

### 使用真实 LLM 驱动

```python
from healthy_agent.kernel import Kernel
from healthy_agent.syscall import io
from healthy_agent.drivers.anthropic import AnthropicDriver

driver = AnthropicDriver(model="claude-sonnet-4-20250514")

async def agent(process, kernel):
    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": "2+2等于几？"}]
    ))
    return result.data["text"]
```

### 命令行

```bash
# 运行任务
healthy-agent run "总结这篇文档" --cores 4 -v

# 使用 Anthropic 驱动
healthy-agent run "写一个函数" --driver anthropic --cores 4

# 使用 DeepSeek / Qwen / Ollama / Zhipu / OpenAI
healthy-agent run "解释 async" --driver deepseek
healthy-agent run "解释量子计算" --driver qwen
```

### Web 服务器 + WebSocket

```bash
# 启动服务器，使用真实 LLM 驱动
healthy-agent serve --driver anthropic --cores 4

# 或使用其他提供者
healthy-agent serve --driver deepseek --model deepseek-chat
healthy-agent serve --driver ollama --model llama3
```

打开 `http://localhost:8000` 使用内置调试 UI，或通过 WebSocket 连接：

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/my-session");
ws.send(JSON.stringify({ prompt: "你好！", mode: "agent" }));
// 接收：thinking → stream 片段 → tool_call 事件 → done
```

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                        用户空间                              │
│  Executor │ Workflow │ MultiAgent │ RAG │ Reflexion          │
├──────────────────────────────────────────────────────────────┤
│                         系统调用                             │
│  fork() │ wait() │ exit() │ io() │ supervised_fork()         │
├──────────────────────────────────────────────────────────────┤
│                          内核                                │
│  ┌───────────┐ ┌────────────┐ ┌─────────────┐ ┌──────────┐ │
│  │  调度器   │ │  核心池    │ │   进程表    │ │ Session  │ │
│  │ (MLFQ)    │ │ (N 核心)   │ │             │ │ Manager  │ │
│  └───────────┘ └────────────┘ └─────────────┘ └──────────┘ │
├──────────────────────────────────────────────────────────────┤
│                         驱动层                               │
│  Anthropic │ OpenAI │ DeepSeek │ Zhipu │ Qwen │ Ollama      │
├──────────────────────────────────────────────────────────────┤
│                      技能与工具                              │
│  file_tools │ shell_tools │ python_eval │ LLM skills         │
├──────────────────────────────────────────────────────────────┤
│          记忆系统         │          IPC / MCP               │
│  短期 │ 长期             │  Channel │ McpServer │ McpClient  │
│ (RAM/ │ (磁盘/           │ (异步    │ (JSON-RPC │ (连接      │
│  TTL) │  Redis/Mem0)     │  消息)   │  stdio)   │  外部服务) │
└──────────────────────────────────────────────────────────────┘
```

## Agent 模式

### Executor（任务执行引擎）

`Executor` 是底层执行引擎，负责 LLM 生成和工具调用。策略层（如 `ReflexionAgent`）位于其上方，决定何时/如何重试。

```python
from healthy_agent.agent import Executor
from healthy_agent.skill import SkillRegistry

skills = SkillRegistry()
skills.load_directory("./skills")

executor = Executor(driver, skills, max_rounds=10)
result = await executor.run("读取 config.yaml 并修复语法错误")
# LLM 自主执行：read_file → 分析 → edit_file → 完成
```

### DAG 工作流

定义带依赖的步骤。无依赖的步骤在不同核心上并行运行。

```python
from healthy_agent.agent import Workflow

wf = Workflow(kernel)
wf.add("fetch", fetch_handler)
wf.add("parse", parse_handler, depends_on=["fetch"])
wf.add("analyze", analyze_handler, depends_on=["fetch"])
wf.add("report", report_handler, depends_on=["parse", "analyze"])
result = await wf.execute(parent_process)
# fetch 先运行，然后 parse+analyze 并行，最后 report
```

### 多 Agent 协调

三种编排多个 Agent 的模式：

```python
from healthy_agent.agent import MultiAgentCoordinator, AgentConfig

coordinator = MultiAgentCoordinator(kernel)

# 并行 —— 所有 Agent 同时运行
result = await coordinator.parallel(agents, parent)

# 流水线 —— 上一个的输出作为下一个的输入
result = await coordinator.pipeline(agents, parent, initial_input="start")

# 辩论 —— Agent 们多轮讨论一个话题
result = await coordinator.debate(agents, parent, topic="最佳方案？", rounds=3)
```

### Supervisor（自动重试）

带自动重试和错误修正的 fork —— 像监控进程重启崩溃的进程，但更智能：会把错误上下文反馈给下一次尝试。

```python
from healthy_agent.syscall import supervised_fork

result = await supervised_fork(
    kernel, parent, "generate_code", payload,
    handler=code_handler,
    max_retries=3,
    judge=judge_fn,  # async (result, payload) → (passed, feedback)
)
```

### RAG（检索增强生成）

内置基于关键词的向量存储，用于上下文检索。生产环境可替换为 chromadb/pinecone。

```python
from healthy_agent.agent import RAGMixin

rag = RAGMixin()
rag.ingest("Healthy Agent 使用 MLFQ 调度")
rag.ingest("进程有 5 个状态：new、ready、running、blocked、terminated")

context = rag.retrieve_context("调度是怎么工作的？")
# 将 context 传入 Executor 或 driver.generate()
```

## LLM 驱动

| 驱动 | 提供者 | 环境变量 | 默认模型 |
|------|--------|---------|---------|
| `AnthropicDriver` | Anthropic Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| `OpenAIDriver` | OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| `DeepSeekDriver` | DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `ZhipuDriver` | 智谱 (GLM) | `ZHIPU_API_KEY` | `glm-4` |
| `QwenDriver` | 通义千问 (DashScope) | `DASHSCOPE_API_KEY` | `qwen-plus` |
| `OllamaDriver` | Ollama（本地） | — | `llama3` |

所有 OpenAI 兼容驱动支持通过 `driver.stream()` 流式输出。

## 技能与工具

两层能力体系：

- **Tool** —— 纯执行，不需要 LLM。输入 → 执行 → 输出。
- **Skill** —— 继承 Tool，增加 LLM 访问，用于智能处理。

内置工具（从 `skills/` 加载）：

| 工具 | 描述 |
|------|------|
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件 |
| `edit_file` | 文件中查找替换 |
| `shell` | 执行 shell 命令 |
| `http_request` | HTTP GET/POST 请求 |
| `python_eval` | 在子进程中运行 Python 代码 |
| `list_dir` | 列出目录内容 |
| `search_text` | 类似 grep 的文本/正则搜索 |

内置 LLM 技能：`summarize`（摘要）、`code_gen`（代码生成）、`web_search`（网页搜索）

自定义技能可通过 `SkillRegistry.load_directory()` 从任意目录加载。

## 记忆系统

两级记忆，灵感来自 RAM + 磁盘：

- **短期记忆** —— 进程内、按 Session 隔离、自动过期（默认 5 分钟 TTL）
- **长期记忆** —— 持久化到磁盘（JSON），重启不丢失

可插拔后端，支持分布式场景：

| 后端 | 存储 | 适用场景 |
|------|------|---------|
| `local`（默认） | JSON 文件 | 单节点、开发环境 |
| `redis` | Redis | 多节点、共享状态 |
| `mem0` | Mem0 AI Memory | 智能长期记忆 |

```python
# 通过 SessionManager
sessions = SessionManager(memory_backend="redis", redis_url="redis://localhost:6379")
session = sessions.create(metadata={"user": "alice"})
session.mem.remember("preference", "dark_mode", persist=True)
value = session.mem.recall("preference")
```

## Session 会话

每个 Session 是一个隔离的执行上下文 —— 类似 Linux 命名空间。独立内存、独立消息历史，不会跨 Session 泄漏。

```python
sessions = SessionManager()
session = sessions.create(metadata={"user": "alice"})
session.add_message("user", "MLFQ 是什么？")
# 消息和记忆都在此 Session 范围内
```

## MCP（模型上下文协议）

通过 MCP JSON-RPC 协议暴露或消费 Agent 能力。

**Server** —— 将工具暴露给外部 MCP 客户端：

```python
from healthy_agent.mcp import McpServer

server = McpServer()
server.register_tool("greet", "打招呼", {"type": "object", "properties": {...}}, handler)
```

**Client** —— 通过子进程 stdio 连接外部 MCP 服务器：

```python
from healthy_agent.mcp import McpClient

client = McpClient()
await client.connect(["python", "-m", "some_mcp_server"])
await client.initialize()
tools = await client.list_tools()
result = await client.call_tool("some_tool", {"arg": "value"})
```

## MLFQ 调度

```
队列0  ██████████  最高优先级  (0.5s 时间片)  ← 新任务、刚从阻塞恢复
队列1  ██████      中优先级    (2s 时间片)    ← 从队列0降级
队列2  ████        低优先级    (10s 时间片)   ← 长时间运行的批量任务
队列3  ██          后台        (无限制)       ← 不可抢占的协调者

         ↑ 每 30s 全局提升（防饥饿）
```

进程从队列 0 进入。如果用满时间片（CPU 密集型），会被降级。提前阻塞的 I/O 密集型进程保留优先级。定期全局提升防止饥饿。

## API 参考

### REST 接口

| 方法 | 路径 | 描述 |
|------|------|------|
| `POST` | `/sessions` | 创建会话 |
| `GET` | `/sessions` | 列出会话 |
| `POST` | `/sessions/{id}/tasks` | 提交任务 |
| `GET` | `/sessions/{id}/tasks/{tid}` | 获取任务结果 |
| `POST` | `/sessions/{id}/memory` | 存储记忆 |
| `GET` | `/sessions/{id}/memory/{key}` | 召回记忆 |
| `GET` | `/sessions/{id}/messages` | 获取消息历史 |
| `GET` | `/skills` | 列出可用技能 |
| `POST` | `/sessions/{id}/skills/{name}` | 调用技能 |
| `GET` | `/kernel/ps` | 进程表 |
| `GET` | `/kernel/stats` | 调度器统计 |
| `WS` | `/ws/{session_id}` | WebSocket 聊天（流式 + Agent 模式） |

### WebSocket 消息

客户端发送：
```json
{"prompt": "你的消息", "mode": "agent"}
```

服务端发送（通过 `msg_id` 标识并发消息）：
- `{"type": "thinking", "msg_id": "..."}` —— 开始处理
- `{"type": "stream", "content": "...", "msg_id": "..."}` —— 流式片段
- `{"type": "tool_call", "name": "...", "input": {...}, "result": "...", "msg_id": "..."}` —— 工具调用
- `{"type": "done", "content": "完整文本", "msg_id": "..."}` —— 响应完成
- `{"type": "error", "content": "...", "msg_id": "..."}` —— 发生错误

## 项目结构

```
src/
├── healthy_agent/
│   ├── kernel/
│   │   ├── process.py      # 进程 + PCB + 状态机
│   │   ├── scheduler.py    # MLFQ 调度器
│   │   ├── core.py         # 核心（执行进程的 worker）
│   │   └── runtime.py      # 内核（总控）
│   ├── syscall/
│   │   ├── api.py          # fork / wait / exit / io
│   │   └── supervisor.py   # supervised_fork（自动重试）
│   ├── agent/
│   │   ├── executor.py     # Executor（任务执行引擎）
│   │   ├── workflow.py     # DAG 工作流引擎
│   │   ├── multi.py        # 多 Agent 协调器
│   │   └── rag.py          # RAG（向量存储 + 检索）
│   ├── drivers/
│   │   ├── base.py         # LLMDriver / ToolDriver 抽象基类
│   │   ├── anthropic.py    # Anthropic Claude 驱动
│   │   ├── openai_compat.py # OpenAI / DeepSeek / Zhipu / Qwen / Ollama
│   │   └── tool_builtin.py # Shell + HTTP 工具驱动
│   ├── skill/
│   │   ├── base.py         # Tool / Skill 基类
│   │   ├── builtin.py      # 内置工具和技能
│   │   └── registry.py     # SkillRegistry（加载、路由、调用）
│   ├── memory/
│   │   ├── store.py        # ShortTermMemory / LongTermMemory / MemoryManager
│   │   └── backend.py      # Redis / Mem0 后端
│   ├── session/
│   │   └── manager.py      # Session + SessionManager
│   ├── mcp/
│   │   ├── protocol.py     # MCP JSON-RPC 协议
│   │   ├── server.py       # McpServer
│   │   └── client.py       # McpClient
│   └── ipc/
│       └── channel.py      # 异步消息通道
├── api/
│   ├── app.py              # FastAPI 应用 + REST + WebSocket
│   └── web.py              # 内置调试 Web UI
└── cli.py                  # CLI（run / serve / ps）
skills/
├── file_tools.py           # read_file, write_file, edit_file, list_dir, search_text
└── shell_tools.py          # shell, http_request, python_eval
```

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT
