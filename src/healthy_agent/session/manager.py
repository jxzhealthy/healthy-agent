from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..memory.store import ShortTermMemory


@dataclass
class Session:
    """Isolated execution context — like a Linux namespace.
    Each session has its own memory, message history, and metadata."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    memory: ShortTermMemory = field(default_factory=ShortTermMemory)
    messages: list[dict] = field(default_factory=list)
    _active: bool = True

    @property
    def active(self) -> bool:
        return self._active

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
            "memory_entries": self.memory.size,
            "metadata": self.metadata,
        }


class SessionManager:
    """Manages multiple isolated sessions — like a container runtime."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, *, session_id: str | None = None, metadata: dict | None = None) -> Session:
        session = Session(metadata=metadata or {})
        if session_id:
            session.session_id = session_id
        self._sessions[session.session_id] = session
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

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values()]

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.active)
