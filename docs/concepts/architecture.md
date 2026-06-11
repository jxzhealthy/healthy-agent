# Architecture Overview

Healthy Agent follows a layered architecture designed for high-concurrency agent execution with resource isolation and fault tolerance.

## Layered Architecture

The system is organized into four primary layers:

**Kernel Layer**: The foundation providing process management, MLFQ scheduling, and virtual core execution. It handles process lifecycle (spawn, schedule, execute, terminate) and resource limits (max processes, spawn rate limiting).

**Scheduler Layer**: Implements Multi-Level Feedback Queue (MLFQ) scheduling with 4 priority levels, time-slice management, priority boosting, and preemption logic. Ensures fair CPU allocation across concurrent agents.

**Core Layer**: Virtual execution cores that run the event loop, dispatch processes from the scheduler, enforce time slices via `asyncio.wait_for`, and handle process state transitions (READY ¡ú RUNNING ¡ú BLOCKED/TERMINATED).

**Process Layer**: Lightweight agent processes with PCB (Process Control Block) tracking state, priority, CPU time, parent-child relationships, and execution context. Each process encapsulates a single agent task.

Data flows downward: Kernel spawns processes ¡ú Scheduler queues them ¡ú Cores execute them ¡ú Processes transition through states. Results flow upward through completion callbacks and Event-based synchronization.

## Module Organization

### drivers

LLM provider abstraction layer supporting OpenAI, Anthropic, Ollama, and custom backends. Handles API communication, token counting, retry logic, and fallback driver switching on failure.

### skills

Plugin system for extending agent capabilities. Skills are Python modules or YAML definitions loaded from configurable directories. Supports hot-reload via file system polling. Skills expose tools/functions that agents can invoke during execution.

### memory

Short-term and long-term memory backend abstraction. Supports local in-memory storage, Redis for distributed scenarios, and Mem0 for semantic memory. Configurable TTL prevents unbounded memory growth.

### compression

Context window management through two-layer compression:

- **Headroom**: Rule-based compression of tool outputs, code blocks, and JSON structures to reduce token usage before LLM calls. Targets ~30% size reduction.
- **Summarization**: LLM-based summarization triggered when context exceeds token threshold. Uses configurable summary model (defaults to primary driver).

### resilience

Fault tolerance mechanisms including exponential backoff retry logic and circuit breaker pattern. Tracks consecutive failures and temporarily halts requests to failing endpoints. Configurable retry counts, delays, and recovery timeouts.

### sandbox

Optional code execution isolation using subprocess or container-based sandboxes. Enforces memory limits, execution timeouts, and prevents unsafe operations. Disabled by default for performance.

### plugins

Extension point for custom integrations. Plugins can hook into kernel events, add new syscall handlers, or provide custom observability exporters.

### observability

Structured logging, metrics collection, and tracing infrastructure. Supports text and JSON log formats. Exposes Prometheus-style metrics for kernel throughput, process latency, error rates, and resource utilization.

## Configuration System

Unified configuration via TOML/YAML files with environment variable overrides (`HEALTHY_AGENT_*` prefix) and CLI parameter support (`--config`). Priority order: CLI args > Environment variables > Config file > Defaults.

All configuration sections map to dataclasses in `src/healthy_agent/config/settings.py`: ServerConfig, KernelConfig, DriverConfig, MemoryConfig, PersistenceConfig, ObservabilityConfig, AuthConfig, SkillsConfig, SandboxConfig, CompressionConfig, HeadroomConfig, ResilienceConfig.

## Execution Flow

1. **Spawn**: Client calls `kernel.spawn()` with task type, payload, and optional handler. Kernel validates resource limits (max processes, spawn rate), creates Process with unique PID, admits to scheduler Q0.

2. **Schedule**: MLFQ scheduler selects highest-priority ready process from queues. Applies priority boost if interval elapsed. Removes process from queue, sets state to RUNNING.

3. **Execute**: Idle core picks scheduled process, runs handler within time slice via `asyncio.wait_for`. Process may complete, timeout (preempted), or block on I/O.

4. **Complete**: Kernel marks process TERMINATED, stores result, decrements active count, signals waiting parent processes via Event, queues PID for deferred reap.

5. **Reap**: Periodic cleanup removes terminated process entries from process table and event registry after TTL expires. Prevents memory leaks from completed processes.

## Performance Optimizations

- **O(1) Active Count**: Kernel tracks active processes via counter instead of scanning process table.
- **Deque-based Spawn Rate**: Sliding window using `deque.popleft()` for amortized O(1) rate limiting.
- **Event-driven Wakeup**: Cores wait on `asyncio.Event` instead of polling, reducing CPU waste when idle.
- **Deferred Reaping**: Terminated processes kept briefly for result retrieval, then batch-cleaned to avoid frequent dict mutations.
- **MLFQ Time Slices**: Short tasks get quick response (Q0: 0.5s), long tasks get fairness (Q3: infinite), preventing starvation.

## Next Steps

- Read [Kernel Concepts](kernel.md) for detailed scheduling and execution mechanics
- Explore [Agent Patterns](patterns.md) for common orchestration strategies
- Review [Configuration Guide](../getting-started/configuration.md) for tuning parameters
