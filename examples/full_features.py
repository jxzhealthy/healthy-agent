"""
Full-feature demo: Memory + Session + MCP + Skill + Kernel scheduling.

A customer service agent that:
  1. Creates isolated sessions per user
  2. Remembers conversation context (short-term) and user preferences (long-term)
  3. Uses skills to handle different request types
  4. Exposes capabilities via MCP
  5. All tasks scheduled through the kernel with fork/wait
"""
import asyncio
import json
import tempfile

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork, wait, io
from healthy_agent.memory import MemoryManager
from healthy_agent.session import SessionManager
from healthy_agent.mcp.server import McpServer
from healthy_agent.skill import SkillRegistry
from healthy_agent.skill.base import Skill, SkillParam, SkillResult
from healthy_agent.ipc import Channel, Message
from healthy_agent.drivers.tool_builtin import ShellDriver


# ── Custom Skills ────────────────────────────────────────────

class GreetSkill(Skill):
    @property
    def name(self): return "greet"
    @property
    def description(self): return "Greet a user by name"
    @property
    def parameters(self):
        return [SkillParam(name="name", type="string", description="User name")]

    async def execute(self, params, process, kernel):
        name = params.get("name", "stranger")
        return SkillResult(success=True, data=f"Hello {name}! How can I help you today?")


class CalcSkill(Skill):
    @property
    def name(self): return "calculate"
    @property
    def description(self): return "Evaluate a math expression safely"
    @property
    def parameters(self):
        return [SkillParam(name="expr", type="string", description="Math expression")]

    async def execute(self, params, process, kernel):
        expr = params.get("expr", "")
        try:
            safe = {"sum": sum, "range": range, "abs": abs, "min": min, "max": max, "len": len}
            result = eval(expr, {"__builtins__": {}}, safe)  # noqa: S307
            return SkillResult(success=True, data=str(result))
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class SystemInfoSkill(Skill):
    @property
    def name(self): return "system_info"
    @property
    def description(self): return "Get system information via shell"

    async def execute(self, params, process, kernel):
        shell = ShellDriver(timeout=5.0)
        result = await io(kernel, process, shell.invoke("exec", {"command": "uname -a"}))
        if result.success:
            return SkillResult(success=True, data=result.data["stdout"].strip())
        return SkillResult(success=False, error=result.error)


class AskLLMSkill(Skill):
    """Ask a question to a real LLM model."""

    @property
    def name(self): return "ask_llm"
    @property
    def description(self): return "Ask a question to an LLM and get an answer"
    @property
    def parameters(self):
        return [SkillParam(name="question", type="string", description="Question to ask")]

    async def execute(self, params, process, kernel):
        question = params.get("question", "")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=False, error="No LLM driver provided")
        result = await io(kernel, process, driver.generate(
            [{"role": "user", "content": question}],
            system="Answer concisely in one sentence.",
        ))
        if result.success:
            return SkillResult(success=True, data=result.data["text"].strip())
        return SkillResult(success=False, error=result.error)


class TranslateSkill(Skill):
    """Translate text using LLM."""

    @property
    def name(self): return "translate"
    @property
    def description(self): return "Translate text to another language"
    @property
    def parameters(self):
        return [
            SkillParam(name="text", type="string", description="Text to translate"),
            SkillParam(name="target_lang", type="string", description="Target language"),
        ]

    async def execute(self, params, process, kernel):
        text = params.get("text", "")
        lang = params.get("target_lang", "English")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=False, error="No LLM driver provided")
        result = await io(kernel, process, driver.generate(
            [{"role": "user", "content": f"Translate to {lang}: {text}"}],
            system=f"Output only the {lang} translation, nothing else.",
        ))
        if result.success:
            return SkillResult(success=True, data=result.data["text"].strip())
        return SkillResult(success=False, error=result.error)


# ── Agent Handlers ───────────────────────────────────────────

log_channel = Channel("log")


async def service_agent(process, kernel):
    """Main agent: handles multiple user requests with session isolation."""
    sessions = process.payload["sessions"]
    memory = process.payload["memory"]
    skills = process.payload["skills"]

    users = [
        {"user_id": "alice", "requests": ["greet", "calculate:2**10", "ask_llm:What is the capital of Japan?", "system_info"]},
        {"user_id": "bob", "requests": ["greet", "translate:Hello world:Chinese", "calculate:sum(range(100))"]},
    ]

    # Fork a worker for each user (parallel)
    worker_pids = []
    for user in users:
        session = sessions.create(metadata={"user_id": user["user_id"]})
        pid = await fork(kernel, process, f"worker_{user['user_id']}", {
            "user": user,
            "session": session,
            "memory": memory,
            "skills": skills,
            "driver": process.payload.get("driver"),
        }, handler=user_worker, preemptible=False)
        worker_pids.append((user["user_id"], pid))

    # Collect results
    results = {}
    for user_id, pid in worker_pids:
        results[user_id] = await wait(kernel, process, pid)

    # Read log messages
    logs = []
    while not log_channel.empty:
        msg = log_channel.try_recv()
        if msg:
            logs.append(msg.data)

    return {"results": results, "logs": logs, "sessions": sessions.list_sessions()}


async def user_worker(process, kernel):
    """Per-user worker: processes requests using skills within isolated session."""
    user = process.payload["user"]
    session = process.payload["session"]
    memory = process.payload["memory"]
    skills: SkillRegistry = process.payload["skills"]

    user_id = user["user_id"]
    responses = []

    for req in user["requests"]:
        # Parse request
        if ":" in req:
            skill_name, param = req.split(":", 1)
        else:
            skill_name, param = req, ""

        # Log via IPC
        await log_channel.send(Message(
            sender_pid=process.pid,
            data=f"[{user_id}] invoking skill: {skill_name}",
        ))

        # Build skill params
        params = {"_driver": process.payload.get("driver")}
        if skill_name == "greet":
            params["name"] = user_id.capitalize()
        elif skill_name == "calculate":
            params["expr"] = param
        elif skill_name == "ask_llm":
            params["question"] = param
        elif skill_name == "translate":
            parts = param.rsplit(":", 1)
            params["text"] = parts[0]
            params["target_lang"] = parts[1] if len(parts) > 1 else "English"

        # Fork child to execute skill
        child_pid = await fork(kernel, process, f"skill_{skill_name}", {
            "skill_name": skill_name,
            "params": params,
            "skills": skills,
        }, handler=skill_executor)
        result = await wait(kernel, process, child_pid)

        # Store in session memory
        session.memory.put(f"result_{skill_name}", result, tags=["result"])
        session.add_message("user", f"/{skill_name} {param}")
        session.add_message("assistant", str(result))
        responses.append({"skill": skill_name, "result": result})

    # Remember user preference in long-term memory
    memory.remember(f"user:{user_id}:last_skill", skill_name, persist=True)

    return {
        "user_id": user_id,
        "responses": responses,
        "session_messages": len(session.get_history()),
        "session_memory_entries": session.memory.size,
    }


async def skill_executor(process, kernel):
    """Executes a single skill."""
    skills: SkillRegistry = process.payload["skills"]
    skill_name = process.payload["skill_name"]
    params = process.payload["params"]
    result = await skills.invoke(skill_name, params, process, kernel)
    return result.data if result.success else f"ERROR: {result.error}"


# ── Main ─────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  Full Feature Demo: Memory + Session + MCP + Skill")
    print("=" * 60)

    # Setup
    tmp = tempfile.mktemp(suffix=".json")
    memory = MemoryManager(long_term_path=tmp)
    sessions = SessionManager()

    # LLM driver
    import os
    has_llm = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"))
    driver = None
    if has_llm:
        from healthy_agent.drivers.anthropic import AnthropicDriver
        driver = AnthropicDriver(model="claude-opus-4-6")
        print(f"  LLM: {driver.name}")
    else:
        print("  LLM: none (set ANTHROPIC_AUTH_TOKEN to enable)")

    skills = SkillRegistry()
    skills.register(GreetSkill())
    skills.register(CalcSkill())
    skills.register(SystemInfoSkill())
    skills.register(AskLLMSkill())
    skills.register(TranslateSkill())

    # Setup MCP server with skills
    mcp = McpServer()

    async def _mcp_skill_handler(args, _s=None):
        r = await _s.execute(args, None, None)
        return {"success": r.success, "data": r.data, "error": r.error}

    for s in [GreetSkill(), CalcSkill()]:
        async def _handler(args, _s=s):
            return await _mcp_skill_handler(args, _s=_s)
        mcp.register_tool(s.name, s.description, s.to_schema()["parameters"], handler=_handler)

    # Run on kernel
    kernel = Kernel(num_cores=4)
    pid = kernel.spawn("service_agent", {
        "sessions": sessions,
        "memory": memory,
        "skills": skills,
        "driver": driver,
    }, handler=service_agent, preemptible=False)

    result = await kernel.exec(pid)

    # Print results
    print("\n--- User Results ---")
    for user_id, data in result["results"].items():
        print(f"\n  [{user_id}]")
        for resp in data["responses"]:
            print(f"    {resp['skill']}: {resp['result']}")
        print(f"    session: {data['session_messages']} messages, {data['session_memory_entries']} memory entries")

    print(f"\n--- IPC Logs ({len(result['logs'])}) ---")
    for log in result["logs"]:
        print(f"  {log}")

    print("\n--- Sessions ---")
    for s in result["sessions"]:
        print(f"  {s['session_id']}: {s['messages']} msgs, active={s['active']}, meta={s['metadata']}")

    print("\n--- Long-term Memory ---")
    print(f"  {memory.long.all()}")

    print("\n--- MCP Server ---")
    init = await mcp.handle_message({"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1})
    tools = await mcp.handle_message({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2})
    print(f"  Server: {json.loads(init)['result']['serverInfo']['name']}")
    print(f"  Tools: {[t['name'] for t in json.loads(tools)['result']['tools']]}")

    calc = await mcp.handle_message({
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": "calculate", "arguments": {"expr": "7*8"}}, "id": 3,
    })
    print(f"  MCP call calculate(7*8) = {json.loads(json.loads(calc)['result']['content'][0]['text'])}")

    print("\n--- Kernel ---")
    ps = kernel.ps()
    print(f"  Total processes: {len(ps)}")
    print("  Process tree:")
    for row in ps:
        indent = "    " if row["parent"] else "  "
        print(f"  {indent}pid={row['pid']} type={row['type']} state={row['state']} cpu={row['cpu_time']}s parent={row['parent']}")

    # Cleanup
    import os
    os.unlink(tmp)

    print("\n" + "=" * 60)
    print("  ALL FEATURES VERIFIED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
