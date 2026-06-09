"""
Example: Real LLM agent running on Healthy Agent kernel.

Demonstrates:
  - Kernel schedules multiple LLM calls across cores
  - Parent agent forks child tasks for parallel LLM queries
  - Shell driver validates generated code in sandbox

Requires: ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL
"""
import asyncio
import re

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait, io
from healthy_agent.drivers.anthropic import AnthropicDriver
from healthy_agent.drivers.tool_builtin import ShellDriver


def strip_markdown(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return blocks[0].strip() if blocks else text.strip()


async def main():
    driver = AnthropicDriver(model="claude-opus-4-6")
    shell = ShellDriver()

    # ── Task 1: Generate code + validate ──────────────────────

    async def codegen_agent(process, kernel):
        """Parent: orchestrates code generation and validation."""
        task = process.payload["task"]

        gen_pid = await fork(
            kernel, process, "llm_generate",
            {"task": task}, handler=generate_handler, preemptible=False,
        )
        code = await wait(kernel, process, gen_pid)

        val_pid = await fork(
            kernel, process, "shell_validate",
            {"code": code, "test": process.payload["test"]},
            handler=validate_handler,
        )
        valid = await wait(kernel, process, val_pid)

        return {"code": code, "valid": valid}

    async def generate_handler(process, kernel):
        """Child: calls LLM to generate code."""
        task = process.payload["task"]
        result = await io(kernel, process, driver.generate(
            [{"role": "user", "content": f"Write a Python function: {task}. Output ONLY raw Python code, no markdown."}],
            system="Output only raw Python code. No markdown, no explanation.",
        ))
        if not result.success:
            return f"# error: {result.error}"
        return strip_markdown(result.data["text"])

    async def validate_handler(process, kernel):
        """Child: runs generated code + test assertions in shell."""
        import tempfile
        import os
        code = process.payload["code"]
        test = process.payload["test"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code + "\n" + test + "\n")
            f.flush()
            path = f.name
        result = await io(kernel, process, shell.invoke("exec", {"command": f"python3 {path}"}))
        os.unlink(path)
        return result.success

    print("=== Task 1: Generate add() + validate ===")
    k1 = Kernel(num_cores=3)
    pid1 = k1.spawn("codegen_agent", {
        "task": "add(a, b) that returns a + b",
        "test": "assert add(2,3)==5\nassert add(-1,1)==0\nprint('OK')",
    }, handler=codegen_agent, preemptible=False)

    result1 = await k1.exec(pid1)
    print(f"  Code: {result1['code']}")
    print(f"  Valid: {result1['valid']}")
    for row in k1.ps():
        print(f"  pid={row['pid']} type={row['type']} state={row['state']} cpu={row['cpu_time']}s")

    # ── Task 2: Parallel LLM queries ─────────────────────────

    async def multi_query_agent(process, kernel):
        """Parent: fans out 3 LLM queries in parallel."""
        questions = process.payload["questions"]
        pids = []
        for q in questions:
            cpid = await fork(
                kernel, process, "llm_query",
                {"question": q}, handler=query_handler,
            )
            pids.append(cpid)

        answers = []
        for cpid in pids:
            answers.append(await wait(kernel, process, cpid))
        return answers

    async def query_handler(process, kernel):
        """Child: asks LLM a question."""
        q = process.payload["question"]
        result = await io(kernel, process, driver.generate(
            [{"role": "user", "content": q}],
            system="Answer concisely in one sentence.",
        ))
        if not result.success:
            return f"error: {result.error}"
        return result.data["text"].strip()

    print("\n=== Task 2: 3 parallel LLM queries ===")
    k2 = Kernel(num_cores=4)
    pid2 = k2.spawn("multi_query", {
        "questions": [
            "What is the capital of France?",
            "What is 12 * 13?",
            "Who wrote Python?",
        ],
    }, handler=multi_query_agent, preemptible=False)

    result2 = await k2.exec(pid2)
    for i, ans in enumerate(result2):
        print(f"  Q{i+1}: {ans}")
    print(f"  Processes: {len(k2.ps())}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
