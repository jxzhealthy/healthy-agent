# Healthy Agent

**A CPU-scheduling-inspired runtime kernel for LLM agent workloads**

Healthy Agent is an innovative agent runtime framework that borrows OS CPU scheduling concepts to provide efficient resource management and task orchestration for LLM agent workloads.

## Core Features

- **Kernel-Level Scheduling**: Priority-based task scheduling with multi-core support
- **Resilient Execution**: Built-in retry, timeout control, and circuit breaking
- **Skill System**: Modular skill management with dynamic loading capabilities
- **Memory Management**: Short-term and long-term memory with context preservation
- **Observability**: Integrated monitoring, structured logging, and metrics collection
- **Multiple Interfaces**: REST API, WebSocket streaming, and Python SDK

## Quick Install

```bash
pip install healthy-agent
```

Or with uv (recommended):

```bash
uv add healthy-agent
```

## Getting Started

Check out the [Quick Start Guide](getting-started/quickstart.md) to run your first agent in minutes.

## Documentation

- **[Installation](getting-started/installation.md)**: Setup and configuration
- **[Architecture](concepts/architecture.md)**: Understand the design principles
- **[Skills Guide](guides/skills.md)**: Build and integrate custom skills
- **[REST API](api/rest.md)**: HTTP endpoint reference
- **[WebSocket API](api/websocket.md)**: Real-time streaming interface
- **[Python SDK](api/python.md)**: Programmatic access
