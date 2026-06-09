from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..kernel.runtime import Kernel
from ..session import SessionManager
from ..skill import SkillRegistry
from ..skill.builtin import SummarizeSkill, CodeGenSkill

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
) -> FastAPI:
    app = FastAPI(
        title="Healthy Agent",
        description="CPU-scheduling-inspired OS kernel for LLM agent workloads",
        version="0.1.0",
    )

    kernel = Kernel(num_cores=num_cores)
    sessions = SessionManager()
    skills = SkillRegistry()
    skills.register(SummarizeSkill())
    skills.register(CodeGenSkill())

    driver = None
    task_results: dict[str, dict] = {}

    @app.on_event("startup")
    async def startup():
        nonlocal driver
        logger.info("Starting Healthy Agent server: cores=%d driver=%s", num_cores, driver_name)
        if driver_name == "anthropic":
            from ..drivers.anthropic import AnthropicDriver
            driver = AnthropicDriver(model=model or "claude-sonnet-4-20250514")
        elif driver_name == "deepseek":
            from ..drivers.openai_compat import DeepSeekDriver
            driver = DeepSeekDriver(model=model or "deepseek-chat")
        elif driver_name == "zhipu":
            from ..drivers.openai_compat import ZhipuDriver
            driver = ZhipuDriver(model=model or "glm-4")
        elif driver_name == "ollama":
            from ..drivers.openai_compat import OllamaDriver
            driver = OllamaDriver(model=model or "llama3")

        async def _kernel_loop():
            kernel._shutdown.clear()
            core_tasks = [asyncio.create_task(c.run_loop()) for c in kernel.cores]
            await kernel._shutdown.wait()
            await asyncio.gather(*core_tasks, return_exceptions=True)

        asyncio.create_task(_kernel_loop())

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
                from ..syscall import io
                result = await io(k, process, driver.generate(
                    [{"role": "user", "content": payload["prompt"]}],
                    system=payload.get("system", "You are a helpful assistant."),
                ))
                session.add_message("user", payload["prompt"])
                text = result.data["text"].strip() if result.success else f"ERROR: {result.error}"
                session.add_message("assistant", text)
                session.mem.remember(f"task:{task_id}", text)
                return text
            return f"[mock] {payload}"

        pid = kernel.spawn(
            req.task_type, req.payload,
            handler=task_handler, preemptible=False,
        )

        async def _wait_result():
            event = kernel._get_event(pid)
            await event.wait()
            result = kernel.process_table[pid].pcb.result
            task_results[task_id] = {
                "status": "completed",
                "result": result if not isinstance(result, Exception) else str(result),
                "pid": pid,
                "cpu_time": kernel.process_table[pid].pcb.cpu_time,
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
        return {"skills": skills.list_skills()}

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
        return {
            "cores": kernel.num_cores,
            "processes": len(kernel.process_table),
            "scheduler": {
                "queues": stats.queue_lengths,
                "scheduled": stats.total_scheduled,
                "preempted": stats.total_preempted,
            },
        }

    return app
