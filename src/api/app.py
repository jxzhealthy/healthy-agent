from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.session import SessionManager
from healthy_agent.skill import SkillRegistry

logger = logging.getLogger("healthy_agent.server")


# ── Request/Response Models ──────────────────────────────────

class CreateSessionRequest(BaseModel):
    metadata: dict[str, Any] = {}


class SubmitTaskRequest(BaseModel):
    task_type: str = "llm_query"
    payload: dict[str, Any] = {}


class MemoryPutRequest(BaseModel):
    key: str
    value: Any
    persist: bool = False
    tags: list[str] = []


class MessageRequest(BaseModel):
    role: str
    content: str


class SkillInvokeRequest(BaseModel):
    name: str
    params: dict[str, Any] = {}


# ── App Factory ──────────────────────────────────────────────

def create_app(
    *,
    num_cores: int = 4,
    driver_name: str = "mock",
    model: str | None = None,
    skills_dir: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Healthy Agent",
        description="CPU-scheduling-inspired OS kernel for LLM agent workloads",
        version="0.1.0",
    )

    from .web import router as web_router
    app.include_router(web_router)

    kernel = Kernel(num_cores=num_cores)
    sessions = SessionManager()
    skills = SkillRegistry()
    import os
    from pathlib import Path
    builtin_skills_dir = Path(__file__).parent.parent.parent / "skills"
    skills.load_directory(builtin_skills_dir)
    extra_skills_dir = skills_dir or os.environ.get("HA_SKILLS_DIR")
    if extra_skills_dir and str(Path(extra_skills_dir).resolve()) != str(builtin_skills_dir.resolve()):
        skills.load_directory(extra_skills_dir)

    driver = None
    task_results: dict[str, dict] = {}

    @app.on_event("startup")
    async def startup():
        nonlocal driver
        logger.info("Starting Healthy Agent server: cores=%d driver=%s", num_cores, driver_name)
        if driver_name == "anthropic":
            from healthy_agent.drivers.anthropic import AnthropicDriver
            driver = AnthropicDriver(model=model or "claude-sonnet-4-20250514")
        elif driver_name == "deepseek":
            from healthy_agent.drivers.openai_compat import DeepSeekDriver
            driver = DeepSeekDriver(model=model or "deepseek-chat")
        elif driver_name == "zhipu":
            from healthy_agent.drivers.openai_compat import ZhipuDriver
            driver = ZhipuDriver(model=model or "glm-4")
        elif driver_name == "qwen":
            from healthy_agent.drivers.openai_compat import QwenDriver
            driver = QwenDriver(model=model or "qwen-plus")
        elif driver_name == "ollama":
            from healthy_agent.drivers.openai_compat import OllamaDriver
            driver = OllamaDriver(model=model or "llama3")

        async def _kernel_loop():
            kernel._shutdown.clear()
            core_tasks = [asyncio.create_task(c.run_loop()) for c in kernel.cores]
            await kernel._shutdown.wait()
            await asyncio.gather(*core_tasks, return_exceptions=True)

        async def _reap_loop():
            while not kernel._shutdown.is_set():
                kernel.reap()
                await asyncio.sleep(30)

        asyncio.create_task(_kernel_loop())
        asyncio.create_task(_reap_loop())

    @app.on_event("shutdown")
    async def shutdown():
        kernel.shutdown()

    # ── Session endpoints ────────────────────────────────────

    @app.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        session = sessions.create(metadata=req.metadata)
        logger.info("Session created: %s meta=%s", session.session_id, req.metadata)
        return {"session_id": session.session_id, **session.to_dict()}

    @app.get("/sessions")
    async def list_sessions():
        return {"sessions": sessions.list_sessions(), "active": sessions.active_count}

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        return session.to_dict()

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        sessions.destroy(session_id)
        return {"deleted": session_id}

    # ── Task endpoints ───────────────────────────────────────

    @app.post("/sessions/{session_id}/tasks")
    async def submit_task(session_id: str, req: SubmitTaskRequest):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")

        task_id = uuid.uuid4().hex[:8]
        logger.info("Task submitted: %s session=%s type=%s", task_id, session_id, req.task_type)
        task_results[task_id] = {"status": "running", "session_id": session_id, "submitted_at": time.time()}

        async def task_handler(process, k):
            payload = process.payload
            if driver and payload.get("prompt"):
                from healthy_agent.syscall import io
                prompt = payload["prompt"]
                session.add_message("user", prompt)

                system_prompt = payload.get("system", "You are a helpful assistant.")
                mem_entries = session.memory.all()
                if mem_entries:
                    system_prompt += "\n\nYou remember the following:\n" + "\n".join(
                        f"- {e.key}: {e.value}" for e in mem_entries
                    )

                result = await io(k, process, driver.generate(
                    [{"role": "user", "content": prompt}],
                    system=system_prompt,
                ))
                text = result.data["text"].strip() if result.success else f"ERROR: {result.error}"
                session.add_message("assistant", text)
                session.memory.put("last_reply", text, tags=["reply"])
                return text
            return f"[mock] {payload}"

        pid = kernel.spawn(
            req.task_type, req.payload,
            handler=task_handler, preemptible=False,
        )

        async def _wait_result():
            try:
                event = kernel._get_event(pid)
                await event.wait()
                process = kernel.process_table.get(pid)
                if process:
                    result = process.pcb.result
                    cpu_time = process.pcb.cpu_time
                else:
                    result = "Process completed (reaped)"
                    cpu_time = 0
                task_results[task_id] = {
                    "status": "completed",
                    "result": result if not isinstance(result, Exception) else str(result),
                    "pid": pid,
                    "cpu_time": cpu_time,
                    "session_id": session_id,
                }
            except Exception as e:
                task_results[task_id] = {
                    "status": "failed",
                    "result": str(e),
                    "pid": pid,
                    "session_id": session_id,
                }

        asyncio.create_task(_wait_result())
        return {"task_id": task_id, "pid": pid, "status": "submitted"}

    @app.get("/sessions/{session_id}/tasks/{task_id}")
    async def get_task(session_id: str, task_id: str):
        if task_id not in task_results:
            raise HTTPException(404, "Task not found")
        return task_results[task_id]

    # ── Memory endpoints ─────────────────────────────────────

    @app.post("/sessions/{session_id}/memory")
    async def memory_put(session_id: str, req: MemoryPutRequest):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session.mem.remember(req.key, req.value, persist=req.persist, tags=req.tags)
        return {"stored": req.key}

    @app.get("/sessions/{session_id}/memory/{key}")
    async def memory_get(session_id: str, key: str):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        value = session.mem.recall(key)
        if value is None:
            raise HTTPException(404, "Key not found")
        return {"key": key, "value": value}

    # ── Message history ──────────────────────────────────────

    @app.post("/sessions/{session_id}/messages")
    async def add_message(session_id: str, req: MessageRequest):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session.add_message(req.role, req.content)
        return {"messages": len(session.messages)}

    @app.get("/sessions/{session_id}/messages")
    async def get_messages(session_id: str, last_n: int | None = None):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        return {"messages": session.get_history(last_n)}

    # ── Skill endpoints ──────────────────────────────────────

    @app.get("/skills")
    async def list_skills():
        all_items = []
        for s in skills._skills.values():
            schema = s.to_schema()
            schema["type"] = "skill" if s.requires_llm else "tool"
            all_items.append(schema)
        return {"skills": all_items}

    @app.post("/sessions/{session_id}/skills/{skill_name}")
    async def invoke_skill(session_id: str, skill_name: str, req: SkillInvokeRequest):
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        params = req.params
        if driver:
            params["_driver"] = driver
        result = await skills.invoke(skill_name, params, None, None)
        return {"success": result.success, "data": result.data, "error": result.error}

    # ── Kernel status ────────────────────────────────────────

    @app.get("/kernel/ps")
    async def kernel_ps():
        return {"processes": kernel.ps()}

    @app.get("/kernel/stats")
    async def kernel_stats():
        stats = kernel.scheduler.stats()
        active = sum(
            1 for p in kernel.process_table.values()
            if p.state.value in ("new", "ready", "running", "blocked")
        )
        return {
            "cores": kernel.num_cores,
            "processes": len(kernel.process_table),
            "active": active,
            "scheduler": {
                "queues": stats.queue_lengths,
                "scheduled": stats.total_scheduled,
                "preempted": stats.total_preempted,
            },
        }

    # ── WebSocket (streaming + agent mode) ─────────────────────

    @app.websocket("/ws/{session_id}")
    async def websocket_chat(websocket: WebSocket, session_id: str):
        session = sessions.get(session_id)
        if not session:
            session = sessions.create(session_id=session_id)

        await websocket.accept()
        logger.info("WebSocket connected: session=%s", session_id)

        try:
            while True:
                data = await websocket.receive_json()
                prompt = data.get("prompt", "")
                mode = data.get("mode", "agent")
                if not prompt:
                    continue

                session.add_message("user", prompt)

                if not driver:
                    await websocket.send_json({"type": "reply", "content": f"[mock] {prompt}"})
                    continue

                system_prompt = "You are a helpful assistant with access to tools. Use them when needed."
                mem_entries = session.memory.all()
                if mem_entries:
                    system_prompt += "\n\nYou remember:\n" + "\n".join(
                        f"- {e.key}: {e.value}" for e in mem_entries
                    )

                if mode == "agent":
                    from healthy_agent.agent import AgentLoop
                    agent = AgentLoop(driver, skills, system_prompt=system_prompt, max_rounds=5)

                    async def on_step(step):
                        if step.role == "tool":
                            await websocket.send_json({
                                "type": "tool_call",
                                "name": step.tool_name,
                                "input": step.tool_input,
                                "result": step.tool_result[:500],
                            })
                        elif step.role == "assistant" and step.content:
                            await websocket.send_json({"type": "stream", "content": step.content})

                    result = await agent.run(prompt, on_step=on_step)
                    text = result.answer
                else:
                    await websocket.send_json({"type": "thinking"})
                    chunks = []
                    async for chunk in driver.stream(
                        [{"role": "user", "content": prompt}],
                        system=system_prompt,
                    ):
                        chunks.append(chunk)
                        await websocket.send_json({"type": "stream", "content": chunk})
                    text = "".join(chunks)

                session.add_message("assistant", text)
                session.memory.put("last_reply", text, tags=["reply"])
                await websocket.send_json({"type": "done", "content": text})

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: session=%s", session_id)

    return app


def app_instance() -> FastAPI:
    """Factory for uvicorn reload mode. Reads config from env vars."""
    import os
    return create_app(
        num_cores=int(os.environ.get("HA_CORES", "4")),
        driver_name=os.environ.get("HA_DRIVER", "mock"),
        model=os.environ.get("HA_MODEL"),
        skills_dir=os.environ.get("HA_SKILLS_DIR"),
    )
