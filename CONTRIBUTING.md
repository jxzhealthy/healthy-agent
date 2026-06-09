# Contributing to Healthy Agent

Thanks for your interest in contributing! This guide covers development setup, coding conventions, and how to extend each subsystem.

## Development Setup

```bash
git clone https://github.com/jxzhealthy/healthy-agent.git
cd healthy-agent
uv sync
```

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Single file
uv run pytest tests/test_kernel.py -v

# With coverage
uv run pytest tests/ --cov=healthy_agent
```

## Linting

```bash
uv run ruff check src/ tests/ examples/ skills/
uv run ruff format src/ tests/ examples/ skills/
uv run ruff check src/ tests/ examples/ skills/ --fix  # auto-fix
```

## Project Structure

```
src/
├── healthy_agent/
│   ├── kernel/          # Process, Scheduler (MLFQ), Core, Kernel
│   ├── syscall/         # fork, wait, exit, io, supervised_fork
│   ├── agent/           # Executor, Reflexion, Workflow, MultiAgent, RAG
│   ├── drivers/         # LLM drivers (Anthropic, OpenAI-compat) + Tool drivers
│   ├── skill/           # Tool/Skill base classes, registry, built-ins
│   ├── memory/          # ShortTermMemory, LongTermMemory, Redis/Mem0 backends
│   ├── session/         # Session + SessionManager (isolated contexts)
│   ├── mcp/             # MCP JSON-RPC protocol, server, client
│   └── ipc/             # Async message channel
├── api/                 # FastAPI app, REST endpoints, WebSocket, debug web UI
└── cli.py               # CLI entry point (run / serve / ps)
skills/                  # Loadable tool plugins (.py) and skill plugins (.md)
skills_examples/         # Example .md skill definitions
examples/                # Runnable example scripts
tests/                   # pytest test suite
```

## Adding a New LLM Driver

There are two base paths:

1. **OpenAI-compatible API** — extend `OpenAICompatDriver` (handles both `generate` and `stream`):

```python
# src/healthy_agent/drivers/openai_compat.py

class YourDriver(OpenAICompatDriver):
    def __init__(self, *, model: str = "your-model", api_key: str | None = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("YOUR_API_KEY", ""),
            base_url="https://api.your-provider.com/v1",
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"your_provider:{self.model}"
```

2. **Custom protocol** — extend `LLMDriver` directly:

```python
# src/healthy_agent/drivers/your_driver.py
from .base import LLMDriver, IOResult

class YourDriver(LLMDriver):
    @property
    def name(self) -> str: return "your_driver"

    async def generate(self, messages: list[dict], **kwargs) -> IOResult:
        # Your API call here
        return IOResult(success=True, data={"text": "...", "tool_calls": []}, tokens_used=0)

    async def stream(self, messages: list[dict], **kwargs):
        # yield text chunks
        yield "chunk"
```

Then register in `src/healthy_agent/drivers/__init__.py`, add to `cli.py` `_make_driver()`, and add to the server startup in `src/api/app.py`.

## Adding a New Tool

Tools are pure execution — no LLM needed. Create a `.py` file in `skills/`:

```python
# skills/my_tools.py
from healthy_agent.skill.base import Tool, SkillParam, SkillResult

class MyTool(Tool):
    @property
    def name(self): return "my_tool"

    @property
    def description(self): return "What the tool does"

    @property
    def parameters(self):
        return [
            SkillParam(name="input", type="string", description="Input data"),
            SkillParam(name="option", type="integer", description="Optional param", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        result = do_something(params["input"])
        return SkillResult(success=True, data=result)
```

The `SkillRegistry.load_directory()` auto-discovers all `Tool` subclasses in `.py` files. No manual registration needed.

## Adding a New Skill (LLM-powered)

Skills extend `Tool` with LLM access. Two approaches:

### Python Skill

```python
from healthy_agent.skill.base import Skill, SkillParam, SkillResult

class MySkill(Skill):
    @property
    def name(self): return "my_skill"

    @property
    def description(self): return "Intelligent processing"

    @property
    def parameters(self):
        return [SkillParam(name="text", type="string", description="Input text")]

    async def execute(self, params, process=None, kernel=None):
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data="[mock] Would use LLM")
        result = await driver.generate(
            [{"role": "user", "content": f"Process: {params['text']}"}],
        )
        return SkillResult(
            success=result.success,
            data=result.data["text"] if result.success else "",
            error=result.error,
        )
```

### Markdown Skill (prompt-only, no code)

Create a `.md` file in `skills/` with YAML frontmatter:

```markdown
---
name: translate
description: Translate text to another language
parameters:
  - name: text
    type: string
    description: Text to translate
    required: true
  - name: language
    type: string
    description: Target language
    required: false
---

# System
You are a professional translator. Translate to {language}.

# Prompt
Translate the following text:

{text}
```

## Adding a New Memory Backend

Extend `MemoryBackend` from `src/healthy_agent/memory/backend.py`:

```python
from healthy_agent.memory.backend import MemoryBackend

class YourBackend(MemoryBackend):
    async def put(self, key, value, *, ttl=None, tags=None) -> None: ...
    async def get(self, key) -> Any | None: ...
    async def delete(self, key) -> None: ...
    async def search(self, tag) -> list[dict]: ...
    async def all(self) -> dict[str, Any]: ...
    async def clear(self) -> None: ...
    async def size(self) -> int: ...
```

Then add the backend selection in `MemoryManager.__init__()` and `SessionManager.create()`.

## Coding Conventions

- **Python 3.11+** — use modern syntax (`X | None`, `list[str]`, `match/case`)
- **Async everywhere** — all I/O operations should be async
- **Type hints** — add return types and parameter types for public APIs
- **Dataclasses** — prefer `@dataclass` for structured data (PCB, IOResult, etc.)
- **Enums** — use `str, Enum` for state machines (like `ProcessState`)
- **Line length** — 100 chars (configured in `pyproject.toml`)
- **Imports** — use `from __future__ import annotations` in modules with forward references
- **No comments unless the WHY is non-obvious** — code should be self-documenting
- **OS metaphors** — keep the naming consistent: processes, cores, drivers, syscalls

## Pull Requests

- One feature per PR
- Include tests for new functionality
- Run `uv run pytest` and `uv run ruff check` before submitting
- Update documentation if you add a new public API
- Keep the OS metaphor consistent across naming and code structure
