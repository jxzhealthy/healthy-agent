from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory.store import ShortTermMemory, MemoryManager


@dataclass
class Session:
    """Isolated execution context — like a Linux namespace.
    Each session has its own memory (short + long), message history, and metadata.
    Memory is fully scoped by session_id — no cross-session leakage."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    memory: ShortTermMemory = field(default_factory=ShortTermMemory)
    _memory_manager: MemoryManager | None = field(default=None, repr=False)
    messages: list[dict] = field(default_factory=list)
    _active: bool = True

    @property
    def active(self) -> bool:
        return self._active

    @property
    def mem(self) -> MemoryManager:
        if self._memory_manager is None:
            raise RuntimeError("Session created without MemoryManager. Use SessionManager.create().")
        return self._memory_manager

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })

    def get_history(self, last_n: int | None = None) -> list[dict]:
        if last_n is None:
            return list(self.messages)
        return self.messages[-last_n:]

    def set_meta(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def get_meta(self, key: str) -> Any | None:
        return self.metadata.get(key)

    def close(self) -> None:
        self._active = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "active": self._active,
            "messages": len(self.messages),
            "memory_short": self.memory.size,
            "memory_backend": self._memory_manager.backend_name if self._memory_manager else "none",
            "metadata": self.metadata,
        }


class SessionManager:
    """Manages multiple isolated sessions — like a container runtime.
    Each session gets its own MemoryManager with isolated namespace."""

    def __init__(
        self,
        *,
        memory_dir: str | Path = "~/.healthy_agent/sessions",
        redis_url: str | None = None,
        memory_backend: str = "local",
    ):
        self._sessions: dict[str, Session] = {}
        self._memory_dir = Path(memory_dir).expanduser()
        self._redis_url = redis_url
        self._memory_backend = memory_backend

    def create(self, *, session_id: str | None = None, metadata: dict | None = None) -> Session:
        sid = session_id or uuid.uuid4().hex[:12]

        if self._memory_backend == "redis" and self._redis_url:
            mm = MemoryManager(
                long_term_path=self._memory_dir / f"{sid}.json",
                backend="redis",
                redis_url=self._redis_url,
            )
        elif self._memory_backend == "mem0":
            mm = MemoryManager(
                long_term_path=self._memory_dir / f"{sid}.json",
                backend="mem0",
                mem0_user_id=sid,
            )
        else:
            mm = MemoryManager(
                long_term_path=self._memory_dir / f"{sid}.json",
            )

        session = Session(
            session_id=sid,
            metadata=metadata or {},
            _memory_manager=mm,
        )
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def close(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.close()

    def destroy(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            session.memory.clear()
            session.close()
            mem_file = self._memory_dir / f"{session_id}.json"
            if mem_file.exists():
                mem_file.unlink()

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.active)
