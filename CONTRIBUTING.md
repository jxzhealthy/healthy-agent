# Contributing to Healthy Agent

## Development Setup

```bash
git clone https://github.com/jxzhealthy/healthy-agent.git
cd healthy-agent
uv sync
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Linting

```bash
uv run ruff check src/ tests/ examples/
uv run ruff check src/ tests/ examples/ --fix  # auto-fix
```

## Project Structure

```
src/healthy_agent/
├── kernel/         # Process, Scheduler, Core, Kernel
├── syscall/        # fork, wait, exit, io
├── drivers/        # LLM and Tool drivers
├── ipc/            # Inter-process channels
└── cli.py          # CLI entry point
```

## Adding a New Driver

1. Create `src/healthy_agent/drivers/your_driver.py`
2. Extend `LLMDriver` or `ToolDriver` from `drivers/base.py`
3. Add to `drivers/__init__.py`
4. Write tests in `tests/`

## Pull Requests

- One feature per PR
- Include tests
- Run `uv run pytest` and `uv run ruff check` before submitting
