"""
Complex scenario: Research → Code Gen → Strict Test → Auto-fix → Report.

Designed to trigger supervised_fork retry:
  The judge runs real assert tests, not just syntax check.
  LLM must produce code that passes edge cases to succeed.

Architecture:
  Coordinator
  ├── Researcher x2 (parallel LLM)
  ├── Synthesizer (LLM)
  ├── CodeGen (supervised_fork, max 4 retries)
  │   ├── Round 1: LLM generates code → judge runs 8 test cases → likely fails
  │   ├── Round 2: LLM gets error feedback → fixes → judge retests
  │   └── Round N: until all tests pass or retries exhausted
  └── Report
"""
import asyncio
import re
import tempfile
import os
import time

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait, io, supervised_fork
from healthy_agent.drivers.anthropic import AnthropicDriver
from healthy_agent.drivers.tool_builtin import ShellDriver
from healthy_agent.memory import MemoryManager
from healthy_agent.session import SessionManager
from healthy_agent.ipc import Channel, Message

driver = AnthropicDriver(model="claude-opus-4-6")
shell = ShellDriver()
log = Channel("log")

TEST_CASES = """
# --- Test cases (must ALL pass) ---
assert merge_sorted_lists([1,3,5], [2,4,6]) == [1,2,3,4,5,6], "basic merge"
assert merge_sorted_lists([], [1,2,3]) == [1,2,3], "empty left"
assert merge_sorted_lists([1,2,3], []) == [1,2,3], "empty right"
assert merge_sorted_lists([], []) == [], "both empty"
assert merge_sorted_lists([1], [1]) == [1,1], "duplicates"
assert merge_sorted_lists([1,1,1], [1,1]) == [1,1,1,1,1], "all same"
assert merge_sorted_lists([-3,-1], [-2,0,4]) == [-3,-2,-1,0,4], "negatives"
assert merge_sorted_lists([100], [1,2,3,99,101]) == [1,2,3,99,100,101], "single vs many"
print("ALL_TESTS_PASSED")
""".strip()


def strip_md(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return blocks[0].strip() if blocks else text.strip()


async def coordinator(process, kernel):
    session = process.payload["session"]
    memory = process.payload["memory"]
    topic = process.payload["topic"]
    task_desc = process.payload["task_desc"]

    await log.send(Message(sender_pid=process.pid, data=f"[coordinator] Start: {topic}"))

    # Phase 1: Research (2 parallel LLM calls)
    await log.send(Message(sender_pid=process.pid, data="[coordinator] Phase 1: Research"))
    r1 = await fork(kernel, process, "research_algo", {
        "q": f"Explain how {topic} works step by step, in 3 sentences.",
    }, handler=researcher)
    r2 = await fork(kernel, process, "research_edge", {
        "q": f"What are common edge cases and pitfalls when implementing {topic}? List 3.",
    }, handler=researcher)

    algo_info = await wait(kernel, process, r1)
    edge_cases = await wait(kernel, process, r2)
    session.mem.remember("algo_info", algo_info, persist=True)
    session.mem.remember("edge_cases", edge_cases, persist=True)
    session.add_message("system", f"Research done: algo={len(algo_info)}chars, edges={len(edge_cases)}chars")

    # Phase 2: Synthesize
    await log.send(Message(sender_pid=process.pid, data="[coordinator] Phase 2: Synthesize"))
    synth_pid = await fork(kernel, process, "synthesizer", {
        "algo": algo_info, "edges": edge_cases, "topic": topic,
    }, handler=synthesizer)
    summary = await wait(kernel, process, synth_pid)
    session.mem.remember("summary", summary)
    session.add_message("assistant", summary)

    # Phase 3: Code generation with STRICT testing (will likely retry)
    await log.send(Message(sender_pid=process.pid, data="[coordinator] Phase 3: Supervised code gen"))
    code_result = await supervised_fork(
        kernel, process, "codegen",
        {"task_desc": task_desc, "summary": summary, "edge_cases": edge_cases},
        handler=code_generator,
        max_retries=4,
        judge=strict_code_judge,
    )
    session.mem.remember("code", code_result.result if code_result.success else "FAILED", persist=True)
    session.add_message("assistant", f"Code gen: {'success' if code_result.success else 'failed'} in {code_result.total_rounds} attempts")

    # Collect logs
    logs = []
    while not log.empty:
        msg = log.try_recv()
        if msg:
            logs.append(msg.data)

    return {
        "topic": topic,
        "summary": summary,
        "code_success": code_result.success,
        "code": code_result.result if code_result.success else None,
        "attempts": [
            {"round": a.round, "success": a.success, "error": a.error[:120] if a.error else "", "feedback": a.feedback[:120] if a.feedback else ""}
            for a in code_result.attempts
        ],
        "total_attempts": code_result.total_rounds,
        "session": session.to_dict(),
        "long_term_memory": session.mem.long.all(),
        "logs": logs,
    }


async def researcher(process, kernel):
    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": process.payload["q"]}],
        system="Be concise and technical.",
    ))
    return result.data["text"].strip() if result.success else f"ERROR: {result.error}"


async def synthesizer(process, kernel):
    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": (
            f"Topic: {process.payload['topic']}\n"
            f"Algorithm:\n{process.payload['algo']}\n"
            f"Edge cases:\n{process.payload['edges']}\n\n"
            "Write a 2-sentence summary combining algorithm logic and edge cases."
        )}],
        system="Exactly 2 sentences.",
    ))
    return result.data["text"].strip() if result.success else f"ERROR: {result.error}"


async def code_generator(process, kernel):
    task_desc = process.payload["task_desc"]
    edge_cases = process.payload.get("edge_cases", "")
    prev_error = process.payload.get("_previous_error", "")
    prev_result = process.payload.get("_previous_result", "")
    retry_round = process.payload.get("_retry_round")

    if prev_error and prev_result:
        prompt = (
            f"Your previous Python code had errors. Fix it.\n\n"
            f"Previous code:\n```python\n{prev_result}\n```\n\n"
            f"Test errors:\n{prev_error}\n\n"
            f"Requirements: {task_desc}\n"
            f"Edge cases to handle: {edge_cases}\n\n"
            f"Output ONLY the fixed Python function, no markdown, no explanation."
        )
        await log.send(Message(sender_pid=process.pid, data=f"[codegen] Retry #{retry_round}: fixing based on test errors"))
    else:
        prompt = (
            f"Write a Python function: {task_desc}\n"
            f"Edge cases to handle: {edge_cases}\n\n"
            f"Output ONLY the Python function definition, no markdown, no explanation, no test code."
        )
        await log.send(Message(sender_pid=process.pid, data="[codegen] Round 1: initial generation"))

    result = await io(kernel, process, driver.generate(
        [{"role": "user", "content": prompt}],
        system="Output only raw Python code. No markdown fences, no explanation, no test code.",
    ))
    if not result.success:
        return f"# error: {result.error}"
    return strip_md(result.data["text"])


async def strict_code_judge(code, payload):
    """Run the code + 8 strict test cases. Must pass ALL to succeed."""
    if not code or code.startswith("# error"):
        return False, f"Generation failed: {code[:100]}"

    full_code = code + "\n\n" + TEST_CASES

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(full_code)
        f.flush()
        path = f.name

    result = await shell.invoke("exec", {"command": f"python3 {path}"})
    os.unlink(path)

    stdout = result.data.get("stdout", "")
    stderr = result.data.get("stderr", "")

    if result.success and "ALL_TESTS_PASSED" in stdout:
        return True, ""

    error_msg = stderr.strip() if stderr.strip() else f"Tests did not pass. stdout: {stdout.strip()}"
    return False, error_msg[:500]


async def main():
    topic = "merging two sorted lists"
    task_desc = "merge_sorted_lists(list1, list2) that merges two sorted lists into one sorted list. Do NOT use built-in sort."

    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    session = sm.create(metadata={"task": topic})

    print("=" * 60)
    print(f"  Complex Task: {topic}")
    print(f"  Kernel: 4 cores | LLM: {driver.name}")
    print(f"  Test cases: 8 strict assertions")
    print("=" * 60)

    kernel = Kernel(num_cores=4)
    t0 = time.monotonic()

    pid = kernel.spawn("coordinator", {
        "topic": topic,
        "task_desc": task_desc,
        "memory": session.mem,
        "session": session,
    }, handler=coordinator, preemptible=False)

    result = await kernel.exec(pid)
    elapsed = time.monotonic() - t0

    # Output
    print(f"\n--- Summary ---")
    print(f"  {result['summary']}")

    print(f"\n--- Code Gen Attempts ---")
    for a in result["attempts"]:
        status = "PASS" if a["success"] else "FAIL"
        detail = a["feedback"] or a["error"] or ""
        print(f"  Round {a['round']}: {status}  {detail}")

    print(f"\n--- Final Code (success={result['code_success']}) ---")
    if result["code"]:
        for line in result["code"].split("\n"):
            print(f"  {line}")
    else:
        print("  [FAILED after all retries]")

    print(f"\n--- Session ---")
    si = result["session"]
    print(f"  ID: {si['session_id']}")
    print(f"  Messages: {si['messages']}, Short memory: {si['memory_short']}, Backend: {si['memory_backend']}")

    print(f"\n--- Long-term Memory ---")
    for k, v in result["long_term_memory"].items():
        preview = str(v)[:80]
        print(f"  {k}: {preview}...")

    print(f"\n--- Process Table ---")
    for row in kernel.ps():
        indent = "    " if row["parent"] else "  "
        print(f"  {indent}pid={row['pid']} type={row['type']} state={row['state']} cpu={row['cpu_time']:.2f}s")

    print(f"\n--- Scheduler ---")
    stats = kernel.scheduler.stats()
    print(f"  Scheduled: {stats.total_scheduled}, Preempted: {stats.total_preempted}")

    print(f"\n--- Timing ---")
    print(f"  Wall time: {elapsed:.1f}s")

    print(f"\n--- Logs ---")
    for l in result["logs"]:
        print(f"  {l}")

    print(f"\n{'=' * 60}")
    print(f"  {'SUCCESS' if result['code_success'] else 'FAILED'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
