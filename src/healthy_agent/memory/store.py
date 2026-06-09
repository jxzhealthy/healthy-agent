from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    key: str
    value: Any
    created_at: float = field(default_factory=time.monotonic)
    ttl: float | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.monotonic() - self.created_at > self.ttl


class ShortTermMemory:
    """RAM — in-process, per-session, auto-expires."""

    def __init__(self, default_ttl: float = 300.0):
        self._store: dict[str, MemoryEntry] = {}
        self._default_ttl = default_ttl

    def put(self, key: str, value: Any, *, ttl: float | None = None, tags: list[str] | None = None) -> None:
        self._store[key] = MemoryEntry(
            key=key, value=value,
            ttl=ttl if ttl is not None else self._default_ttl,
            tags=tags or [],
        )

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expired:
            del self._store[key]
            return None
        return entry.value

    def search(self, tag: str) -> list[MemoryEntry]:
        self._gc()
        return [e for e in self._store.values() if tag in e.tags]

    def all(self) -> list[MemoryEntry]:
        self._gc()
        return list(self._store.values())

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        self._gc()
        return len(self._store)

    def _gc(self) -> None:
        expired = [k for k, v in self._store.items() if v.expired]
        for k in expired:
            del self._store[k]


class LongTermMemory:
    """Disk — persisted to JSON file, survives restarts."""

    def __init__(self, path: str | Path = "~/.healthy_agent/memory.json"):
        self._path = Path(path).expanduser()
        self._store: dict[str, Any] = {}
        self._load()

    def put(self, key: str, value: Any, *, tags: list[str] | None = None) -> None:
        self._store[key] = {
            "value": value,
            "tags": tags or [],
            "updated_at": time.time(),
        }
        self._save()

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        return entry["value"] if entry else None

    def search(self, tag: str) -> list[dict]:
        return [
            {"key": k, **v}
            for k, v in self._store.items()
            if tag in v.get("tags", [])
        ]

    def all(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in self._store.items()}

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._save()

    def clear(self) -> None:
        self._store.clear()
        self._save()

    @property
    def size(self) -> int:
        return len(self._store)

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._store = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._store = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._store, ensure_ascii=False, indent=2))


class MemoryManager:
    """Unified interface — short-term (RAM) + long-term (disk or Redis)."""

    def __init__(
        self,
        *,
        short_term_ttl: float = 300.0,
        long_term_path: str | Path = "~/.healthy_agent/memory.json",
        redis_url: str | None = None,
    ):
        self.short = ShortTermMemory(default_ttl=short_term_ttl)
        self._redis_backend = None
        if redis_url:
            from .backend import RedisMemoryBackend
            self._redis_backend = RedisMemoryBackend(redis_url)
        self.long = LongTermMemory(path=long_term_path)

    def remember(self, key: str, value: Any, *, persist: bool = False, tags: list[str] | None = None) -> None:
        self.short.put(key, value, tags=tags)
        if persist:
            self.long.put(key, value, tags=tags)

    async def remember_async(self, key: str, value: Any, *, persist: bool = False, ttl: int | None = None, tags: list[str] | None = None) -> None:
        self.short.put(key, value, tags=tags)
        if persist and self._redis_backend:
            await self._redis_backend.put(key, value, ttl=ttl, tags=tags)
        elif persist:
            self.long.put(key, value, tags=tags)

    def recall(self, key: str) -> Any | None:
        value = self.short.get(key)
        if value is not None:
            return value
        return self.long.get(key)

    async def recall_async(self, key: str) -> Any | None:
        value = self.short.get(key)
        if value is not None:
            return value
        if self._redis_backend:
            return await self._redis_backend.get(key)
        return self.long.get(key)

    def forget(self, key: str, *, persistent: bool = False) -> None:
        self.short.delete(key)
        if persistent:
            self.long.delete(key)

    async def forget_async(self, key: str, *, persistent: bool = False) -> None:
        self.short.delete(key)
        if persistent and self._redis_backend:
            await self._redis_backend.delete(key)
        elif persistent:
            self.long.delete(key)

    @property
    def distributed(self) -> bool:
        return self._redis_backend is not None
