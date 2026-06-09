from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    sender_pid: int
    data: Any
    timestamp: float = field(default_factory=time.monotonic)
    channel: str = ""


class Channel:
    """Unbounded async channel for inter-process communication."""

    def __init__(self, name: str, capacity: int = 0):
        self.name = name
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=capacity)

    async def send(self, msg: Message) -> None:
        msg.channel = self.name
        await self._queue.put(msg)

    async def recv(self, timeout: float | None = None) -> Message | None:
        try:
            if timeout:
                return await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return await self._queue.get()
        except asyncio.TimeoutError:
            return None

    def try_recv(self) -> Message | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        return self._queue.empty()
