from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any


class MemoryBackend(ABC):
    """Abstract backend for both short-term and long-term memory."""

    @abstractmethod
    async def put(self, key: str, value: Any, *, ttl: int | None = None, tags: list[str] | None = None) -> None:
        ...

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def search(self, tag: str) -> list[dict]:
        ...

    @abstractmethod
    async def all(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def clear(self) -> None:
        ...

    @abstractmethod
    async def size(self) -> int:
        ...


class RedisMemoryBackend(MemoryBackend):
    """Redis-backed memory — distributed, supports TTL natively."""

    def __init__(self, redis_url: str = "redis://localhost:6379", *, prefix: str = "ha:mem:"):
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._tags_key = f"{prefix}_tags"

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def put(self, key: str, value: Any, *, ttl: int | None = None, tags: list[str] | None = None) -> None:
        data = json.dumps({"value": value, "tags": tags or [], "ts": time.time()})
        if ttl:
            await self._client.set(self._key(key), data, ex=ttl)
        else:
            await self._client.set(self._key(key), data)
        if tags:
            for tag in tags:
                await self._client.sadd(f"{self._tags_key}:{tag}", key)

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw).get("value")

    async def delete(self, key: str) -> None:
        raw = await self._client.get(self._key(key))
        if raw:
            entry = json.loads(raw)
            for tag in entry.get("tags", []):
                await self._client.srem(f"{self._tags_key}:{tag}", key)
        await self._client.delete(self._key(key))

    async def search(self, tag: str) -> list[dict]:
        keys = await self._client.smembers(f"{self._tags_key}:{tag}")
        results = []
        for key in keys:
            raw = await self._client.get(self._key(key))
            if raw:
                entry = json.loads(raw)
                results.append({"key": key, **entry})
        return results

    async def all(self) -> dict[str, Any]:
        cursor = 0
        result = {}
        while True:
            cursor, keys = await self._client.scan(cursor=cursor, match=f"{self._prefix}*", count=100)
            for full_key in keys:
                fk = full_key if isinstance(full_key, str) else full_key.decode()
                if fk.startswith(self._tags_key):
                    continue
                short_key = fk[len(self._prefix):]
                raw = await self._client.get(fk)
                if raw:
                    result[short_key] = json.loads(raw).get("value")
            if not cursor:
                break
        return result

    async def clear(self) -> None:
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(cursor=cursor, match=f"{self._prefix}*", count=100)
            if keys:
                await self._client.delete(*keys)
            if not cursor:
                break

    async def size(self) -> int:
        count = 0
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(cursor=cursor, match=f"{self._prefix}*", count=100)
            for k in keys:
                fk = k if isinstance(k, str) else k.decode()
                if not fk.startswith(self._tags_key):
                    count += 1
            if not cursor:
                break
        return count

    async def close(self) -> None:
        await self._client.aclose()


class Mem0Backend(MemoryBackend):
    """Mem0-backed memory — vector search, auto-extraction, user-scoped.

    Requires: pip install mem0ai
    """

    def __init__(self, *, user_id: str = "default", config: dict | None = None):
        try:
            from mem0 import Memory
        except ImportError:
            raise ImportError("mem0ai is required: pip install mem0ai")
        self._mem = Memory.from_config(config) if config else Memory()
        self._user_id = user_id

    async def put(self, key: str, value: Any, *, ttl: int | None = None, tags: list[str] | None = None) -> None:
        text = value if isinstance(value, str) else json.dumps(value)
        metadata = {"key": key}
        if tags:
            metadata["tags"] = ",".join(tags)
        self._mem.add(text, user_id=self._user_id, metadata=metadata)

    async def get(self, key: str) -> Any | None:
        results = self._mem.search(key, user_id=self._user_id, limit=1)
        if not results or not results.get("results"):
            return None
        top = results["results"][0]
        return top.get("memory", top.get("text"))

    async def delete(self, key: str) -> None:
        results = self._mem.search(key, user_id=self._user_id, limit=5)
        for item in results.get("results", []):
            mid = item.get("id")
            if mid:
                self._mem.delete(mid)

    async def search(self, tag: str) -> list[dict]:
        results = self._mem.search(tag, user_id=self._user_id, limit=20)
        return [
            {"key": r.get("metadata", {}).get("key", ""), "value": r.get("memory", r.get("text", ""))}
            for r in results.get("results", [])
        ]

    async def all(self) -> dict[str, Any]:
        results = self._mem.get_all(user_id=self._user_id)
        out = {}
        for r in results.get("results", []):
            key = r.get("metadata", {}).get("key", r.get("id", ""))
            out[key] = r.get("memory", r.get("text", ""))
        return out

    async def clear(self) -> None:
        self._mem.delete_all(user_id=self._user_id)

    async def size(self) -> int:
        results = self._mem.get_all(user_id=self._user_id)
        return len(results.get("results", []))
