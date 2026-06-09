"""
Complex scenario: Multi-agent research assistant.

Architecture:
                        ┌──────────────┐
                        │  Coordinator │ pid=1
                        └──────┬───────┘
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
        ┌────────────┐  ┌────────────┐  ┌────────────┐
        │ Researcher │  │ Researcher │  │ Researcher │  pid=2,3,4
        │ (history)  │  │ (science)  │  │ (culture)  │
        └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
               │               │               │
               │  IPC channel  │               │
               └───────┬───────┘               │
                       ▼                       │
               ┌──────────────┐                │
               │  Fact Checker │ pid=5          │
               │  (Shell exec) │               │
               └──────┬───────┘                │
                      │                        │
                      └────────┬───────────────┘
                               ▼
                       ┌──────────────┐
                       │ Synthesizer  │ pid=6
                       │ (LLM merge)  │
                       └──────────────┘

Exercises:
  - 3-level process tree
  - 3 parallel LLM calls (researchers)
  - IPC channel (researchers → fact checker)
  - Shell driver (fact checker runs Python to verify)
  - LLM synthesizer combines results
  - Error handling (one researcher may fail)
  - MLFQ: short tasks stay high priority, LLM calls get scheduled fairly
"""
import asyncio
import json
import time

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait, io
from healthy_agent.drivers.anthropic import AnthropicDriver
from healthy_agent.drivers.tool_builtin import ShellDriver
from healthy_agent.ipc import Channel, Message


driver = AnthropicDriver(model="claude-opus-4-6")
shell = ShellDriver()
progress_channel = Channel("progress")


# ── Coordinator ──────────────────────────────────────────────

async def coordinator(process, kernel):
    """Top-level: dispatches researchers, fact-checks, synthesizes."""
    topic = process.payload["topic"]
    print(f"\n  [Coordinator] Starting research on: {topic}")

    # Phase 1: Fork 3 researchers in parallel
    angles = [
        {"angle": "history", "prompt": f"What are 3 key historical facts about {topic}? Be concise, 1-2 sentences each."},
        {"angle": "science", "prompt": f"What are 3 key scientific facts about {topic}? Be concise, 1-2 sentences each."},
        {"angle": "culture", "prompt": f"What are 3 key cultural facts about {topic}? Be concise, 1-2 sentences each."},
    ]

    researcher_pids = []
    for a in angles:
        pid = await fork(kernel, process, f"researcher_{a['angle']}", a, handler=researcher)
        researcher_pids.append((a["angle"], pid))

    # Collect results (parallel wait)
    findings = {}
    for angle, pid in researcher_pids:
        result = await wait(kernel, process, pid)
        findings[angle] = result
        print(f"  [Coordinator] Got {angle} findings ({len(result)} chars)")

    # Phase 2: Fact check — verify one claim via Shell
    checker_pid = await fork(
        kernel, process, "fact_checker",
        {"findings": findings},
        handler=fact_checker,
    )
    check_result = await wait(kernel, process, checker_pid)
    print(f"  [Coordinator] Fact check: {check_result}")

    # Phase 3: Read progress messages from IPC
    messages = []
    while not progress_channel.empty:
        msg = progress_channel.try_recv()
        if msg:
            messages.append(msg.data)

    # Phase 4: Synthesize all findings into a summary
    synth_pid = await fork(
        kernel, process, "synthesizer",
        {"topic": topic, "findings": findings, "check": check_result},
        handler=synthesizer,
        preemptible=False,
    )
    summary = await wait(kernel, process, synth_pid)

    return {
        "topic": topic,
        "findings": findings,
        "fact_check": check_result,
        "progress_messages": len(messages),
        "summary": summary,
    }


# ── Researcher ───────────────────────────────────────────────

async def researcher(process, kernel):
    """Child: queries LLM for facts about one angle of the topic."""
    angle = process.payload["angle"]
    prompt = process.payload["prompt"]

    # Report progress via IPC
    await progress_channel.send(Message(
        sender_pid=process.pid,
        data=f"researcher_{angle}: starting",
    ))

    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": prompt}],
        system="You are a research assistant. Be factual and concise.",
    ))

    await progress_channel.send(Message(
        sender_pid=process.pid,
        data=f"researcher_{angle}: done (tokens={result.tokens_used})",
    ))

    if not result.success:
        return f"[ERROR] {result.error}"
    return result.data["text"].strip()


# ── Fact Checker ─────────────────────────────────────────────

async def fact_checker(process, kernel):
    """Child: uses Shell to run a Python script that validates data structure."""
    import tempfile
    import os
    findings = process.payload["findings"]

    check_code = """
import json, sys
findings = json.loads(sys.stdin.read())
errors = []
for angle, text in findings.items():
    if not text or len(text) < 20:
        errors.append(f"{angle}: too short or empty")
    if "[ERROR]" in text:
        errors.append(f"{angle}: contains error")
if errors:
    print("FAIL: " + "; ".join(errors))
else:
    print(f"PASS: all {len(findings)} findings valid, total {sum(len(v) for v in findings.values())} chars")
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as script:
        script.write(check_code)
        script.flush()
        script_path = script.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as data:
        json.dump(findings, data)
        data.flush()
        data_path = data.name

    result = await io(kernel, process, shell.invoke("exec", {
        "command": f"python3 {script_path} < {data_path}"
    }))
    os.unlink(script_path)
    os.unlink(data_path)
    return result.data["stdout"].strip() if result.success else f"CHECK_ERROR: {result.error}"


# ── Synthesizer ──────────────────────────────────────────────

async def synthesizer(process, kernel):
    """Child: calls LLM to merge all findings into a coherent summary."""
    topic = process.payload["topic"]
    findings = process.payload["findings"]
    check = process.payload["check"]

    combined = "\n\n".join(f"### {k.title()}\n{v}" for k, v in findings.items())
    prompt = f"""Topic: {topic}

Research findings:
{combined}

Quality check: {check}

Write a concise 3-sentence summary combining these findings."""

    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": prompt}],
        system="Write a concise summary. 3 sentences max.",
    ))
    if not result.success:
        return f"[ERROR] {result.error}"
    return result.data["text"].strip()


# ── Main ─────────────────────────────────────────────────────

async def main():
    topic = "the Great Wall of China"

    print("=" * 60)
    print(f"  Research Agent — Topic: {topic}")
    print("  Kernel: 4 cores, MLFQ scheduler")
    print("=" * 60)

    kernel = Kernel(num_cores=4)

    # Track scheduling events
    events_log = []
    def on_event(event_type, process):
        events_log.append((time.monotonic(), event_type, process.pid, process.task_type))

    kernel._on_event = on_event

    t0 = time.monotonic()
    pid = kernel.spawn("coordinator", {"topic": topic}, handler=coordinator, preemptible=False)
    result = await kernel.exec(pid)
    total = time.monotonic() - t0

    # Print results
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    print(f"\n  Topic: {result['topic']}")
    print(f"  Fact check: {result['fact_check']}")
    print(f"  IPC messages received: {result['progress_messages']}")

    print("\n  --- Summary ---")
    print(f"  {result['summary']}")

    print("\n  --- Process Table ---")
    print(f"  {'PID':<5} {'Type':<20} {'State':<12} {'Priority':<9} {'CPU(s)':<10} {'Parent'}")
    print(f"  {'-'*70}")
    for row in kernel.ps():
        print(f"  {row['pid']:<5} {row['type']:<20} {row['state']:<12} {row['priority']:<9} {row['cpu_time']:<10} {row['parent']}")

    print("\n  --- Scheduler Stats ---")
    stats = kernel.scheduler.stats()
    print(f"  Total scheduled: {stats.total_scheduled}")
    print(f"  Total preempted: {stats.total_preempted}")
    print(f"  Total boosted:   {stats.total_boosted}")

    print("\n  --- Timing ---")
    print(f"  Total wall time: {total:.2f}s")

    # Show scheduling event timeline
    if events_log:
        print("\n  --- Scheduling Events (first 15) ---")
        t_base = events_log[0][0]
        for t, etype, pid, ttype in events_log[:15]:
            print(f"  +{t - t_base:.3f}s  [{etype}] pid={pid} ({ttype})")

    print()


if __name__ == "__main__":
    asyncio.run(main())
