# Kernel Concepts

The Kernel is the core execution engine of Healthy Agent, providing process management, MLFQ scheduling, and virtual core execution for concurrent agent tasks.

## Kernel Class

The `Kernel` class in `src/healthy_agent/kernel/runtime.py` orchestrates the entire system:

**spawn(task_type, payload, handler, parent_pid, preemptible)**: Creates a new process with unique PID. Validates resource limits (max_processes, max_spawn_rate), increments active count, admits to scheduler Q0, signals cores via Event. Returns PID. Raises `ResourceError` if limits exceeded.

**run()**: Main kernel entry point. Starts all core event loops concurrently via `asyncio.create_task`. Waits on shutdown signal. Gracefully stops cores and gathers tasks.

**exec(pid)**: Executes a single process synchronously from caller perspective. Starts cores, waits on process completion Event, returns result. Used for blocking execution semantics.

**wait_pid(pid)**: Blocks caller until specified process completes. Uses per-process asyncio.Event for synchronization. Returns process result.

**shutdown()**: Sets shutdown flag to signal all cores to stop accepting new work. Cores finish current time slice then exit loop.

**reap()**: Cleans up terminated processes from process table and event registry. Uses deferred reaping with TTL (60s default) to allow result retrieval. Returns count of reaped processes.

**ps()**: Returns list of process snapshots with pid, type, state, priority, cpu_time, and parent. Useful for debugging and observability.

**_complete(process, result)**: Internal callback invoked when process finishes. Sets TERMINATED state, stores result, decrements active count, records metrics, signals waiters, queues for reap. Handles both success and exception results.

**io_complete(process, result)**: Resumes blocked process after I/O operation completes. Unblocks process back to scheduler at same priority level, signals work available.

## MLFQ Scheduler

The `MLFQScheduler` in `src/healthy_agent/kernel/scheduler.py` implements Multi-Level Feedback Queue scheduling with 4 priority levels:

**Queue Structure**: Four deques representing Q0 (highest priority) through Q3 (lowest). New processes enter Q0 with 0.5s time slice. Preempted processes demote one level. Long-running CPU-bound tasks eventually reach Q3 with infinite time slice.

**Time Slices**: Default slices are [0.5s, 2.0s, 10.0s, ¡Þ]. Short tasks get quick response; long tasks get fairness without starvation. Non-preemptible tasks (preemptible=False) receive infinite time slice regardless of level.

**admit(process)**: Adds new process to Q0, sets priority=0, time_slice=0.5s, state=READY.

**schedule()**: Scans queues from Q0 to Q3, returns first available process. Sets state to RUNNING. Triggers priority boost check before selection.

**preempt(process)**: Demotes process one level (capped at Q3), updates time slice, sets READY, appends to target queue. Logs transition for observability.

**unblock(process)**: Returns blocked process to same priority queue with original time slice. State transitions BLOCKED ¡ú READY.

**boost()**: Periodically promotes all non-Q0 processes back to Q0 to prevent starvation of long-running tasks. Triggered every `boost_interval` seconds (default 30s). Logs promotion count.

**_maybe_boost()**: Checks elapsed time since last boost, invokes boost() if interval exceeded. Called lazily during schedule() to avoid background threads.

**stats**: Tracks total_scheduled, total_preempted, total_boosted counts. Exposes queue_lengths for monitoring queue depth distribution.

## Core Execution Loop

Each `Core` in `src/healthy_agent/kernel/core.py` runs an independent async event loop:

**run_loop()**: Infinite loop while core is running. Calls scheduler.schedule() to fetch next ready process. If no work available and shutdown not signaled, clears work_available Event and waits with 50ms timeout (Event-driven wakeup prevents busy-waiting).

**Execution**: Dispatches process.execute(kernel) within time slice using `asyncio.wait_for`. Tracks CPU time via monotonic clock. On success, calls kernel._complete(). On TimeoutError, calls scheduler.preempt(). On BlockedError, leaves process blocked for I/O completion. On Exception, completes with error result.

**Resource Tracking**: Increments total_executed counter per completed process. Logs dispatch and preemption events at DEBUG level for troubleshooting.

**stop()**: Sets _running=False to exit loop. Invoked during kernel shutdown.

## Process Lifecycle

Processes in `src/healthy_agent/kernel/process.py` follow strict state machine:

**NEW**: Initial state after spawn. Immediately transitions to READY upon scheduler admission.

**READY**: Queued in MLFQ, awaiting core assignment. Can be promoted/demoted by scheduler.

**RUNNING**: Assigned to core, actively executing. Subject to time slice preemption.

**BLOCKED**: Waiting for I/O or external event. Removed from scheduler queues. Resumed via io_complete() or unblock().

**TERMINATED**: Execution complete (success or failure). Result stored in PCB. Pending reap cleanup.

**PCB (Process Control Block)**: Dataclass tracking pid, parent_pid, state, priority, created_at, started_at, cpu_time, time_slice, block_reason, context dict, result, children list, task_type. Separates metadata from process logic for clean scheduling decisions.

**Process.execute(kernel)**: Invokes handler coroutine if provided, otherwise returns None. Records started_at timestamp. Handler receives (process, kernel) arguments for syscall access.

**block(reason)**: Transitions to BLOCKED state, stores reason string. Core catches BlockedError to halt execution without preemption penalty.

**terminate(result)**: Direct termination bypassing normal completion flow. Rarely used externally.

## Performance Optimizations

**O(1) Active Count**: Kernel maintains `_active_count` integer incremented/decremented on spawn/complete. Avoids O(n) process table scans for limit checks.

**Deque Spawn Rate**: `_spawn_timestamps` deque stores recent spawn times. Sliding window via `popleft()` removes entries older than 1 second. Amortized O(1) rate limiting vs O(n) list filtering.

**Event-driven Wakeup**: Cores wait on `_work_available` asyncio.Event instead of polling scheduler. Spawn/unblock/io_complete set the Event to wake idle cores immediately. Reduces CPU waste during low load.

**Deferred Reaping**: Terminated processes retained in process_table for 60s to allow result retrieval via wait_pid/exec. Batch cleanup via reap() avoids frequent dict mutations under high throughput.

**MLFQ Time Slices**: Adaptive scheduling balances responsiveness (short tasks finish quickly in Q0) and fairness (long tasks progress in Q3 without starvation). Priority boost prevents indefinite demotion.

**Monotonic Clock**: All timing uses `time.monotonic()` immune to system clock adjustments. Ensures accurate CPU time accounting and timeout enforcement.

## Next Steps

- Read [Architecture Overview](architecture.md) for system-wide design
- Explore [Agent Patterns](patterns.md) for orchestration strategies
- Review [Configuration Guide](../getting-started/configuration.md) for kernel tuning parameters (num_cores, max_processes, max_spawn_rate)
