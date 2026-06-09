from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    sender_pid: int
    data: Any
    timestamp: float = field(default_factory=time.monotonic)
    channel: str = ""
    topic: str = ""


class Channel:
    """Async channel for inter-process communication.

    Supports point-to-point messaging with optional message history.
    """

    def __init__(self, name: str, capacity: int = 0, history_size: int = 0):
        self.name = name
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=capacity)
        self._history: deque[Message] = deque(maxlen=history_size or None) if history_size > 0 else deque(maxlen=0)
        self._history_enabled = history_size > 0

    async def send(self, msg: Message) -> None:
        msg.channel = self.name
        if self._history_enabled:
            self._history.append(msg)
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

    def get_history(self, last_n: int | None = None) -> list[Message]:
        """Return recent message history."""
        if not self._history_enabled:
            return []
        items = list(self._history)
        if last_n is not None:
            return items[-last_n:]
        return items

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        return self._queue.empty()


class BroadcastChannel:
    """Pub/sub channel: one sender, multiple subscribers.

    Each subscriber gets its own queue, so messages are delivered to all.

    Example:
        broadcast = BroadcastChannel("events")
        sub1 = broadcast.subscribe("agent_1")
        sub2 = broadcast.subscribe("agent_2")
        await broadcast.publish(Message(sender_pid=0, data="hello"))
        msg1 = await sub1.recv()  # "hello"
        msg2 = await sub2.recv()  # "hello"
    """

    def __init__(self, name: str, capacity: int = 0):
        self.name = name
        self._capacity = capacity
        self._subscribers: dict[str, asyncio.Queue] = {}

    def subscribe(self, subscriber_id: str) -> BroadcastSubscription:
        """Create a subscription for a subscriber."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._capacity)
        self._subscribers[subscriber_id] = queue
        return BroadcastSubscription(subscriber_id, queue, self)

    def unsubscribe(self, subscriber_id: str) -> None:
        self._subscribers.pop(subscriber_id, None)

    async def publish(self, msg: Message) -> int:
        """Publish a message to all subscribers. Returns number of recipients."""
        msg.channel = self.name
        delivered = 0
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(msg)
                delivered += 1
            except asyncio.QueueFull:
                pass
        return delivered

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class BroadcastSubscription:
    """A single subscriber's view of a BroadcastChannel."""

    def __init__(self, subscriber_id: str, queue: asyncio.Queue, parent: BroadcastChannel):
        self.subscriber_id = subscriber_id
        self._queue = queue
        self._parent = parent

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

    def unsubscribe(self) -> None:
        self._parent.unsubscribe(self.subscriber_id)

    @property
    def pending(self) -> int:
        return self._queue.qsize()


class TopicRouter:
    """Route messages to different channels based on topic.

    Example:
        router = TopicRouter()
        router.register("errors", error_channel)
        router.register("metrics", metrics_channel)
        await router.route(Message(sender_pid=0, data="oops", topic="errors"))
    """

    def __init__(self):
        self._routes: dict[str, Channel] = {}
        self._default: Channel | None = None

    def register(self, topic: str, channel: Channel) -> None:
        self._routes[topic] = channel

    def set_default(self, channel: Channel) -> None:
        self._default = channel

    async def route(self, msg: Message) -> bool:
        """Route a message to the channel matching its topic. Returns True if delivered."""
        target = self._routes.get(msg.topic) or self._default
        if target is None:
            return False
        await target.send(msg)
        return True

    @property
    def topics(self) -> list[str]:
        return list(self._routes.keys())
