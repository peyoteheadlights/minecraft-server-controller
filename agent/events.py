"""A small async pub/sub bus.

Subscribers never block publishers: each websocket owns a bounded queue and a
slow consumer drops its oldest item rather than stalling the agent. A handler
that raises is logged and ignored - notifications must never take the agent
down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Event:
    type: str
    message: str = ""
    level: str = "info"  # info | success | warn | error
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "level": self.level,
            "data": self.data,
            "ts": self.ts,
        }


Handler = Callable[[Event], "Awaitable[None] | None"]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self, handler: Handler) -> Handler:
        self._handlers.append(handler)
        return handler

    def unsubscribe(self, handler: Handler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def queue(self, maxsize: int = 500) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues.add(q)
        return q

    def release(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    async def publish(self, event: Event) -> None:
        for q in list(self._queues):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - race
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - race
                pass
        for handler in list(self._handlers):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("event handler failed for %s", event.type)

    def publish_soon(self, event: Event) -> None:
        """Fire-and-forget publish, safe to call from sync code."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(event))
