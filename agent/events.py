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


# Recorded as the server_id of events about the agent itself rather than
# one Minecraft server (sign-in failures, certificates, the agent starting).
# Server ids cannot start with "_", so this never collides with one.
AGENT_SCOPE = "_agent"


@dataclass
class Event:
    type: str
    message: str = ""
    level: str = "info"  # info | success | warn | error
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    # Which Minecraft server this is about. Filled in by the server's
    # ServerBus; None means the event is about the agent as a whole.
    server_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "level": self.level,
            "data": self.data,
            "ts": self.ts,
            "server_id": self.server_id,
        }


Handler = Callable[[Event], "Awaitable[None] | None"]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        # Each queue with the filter that decides what it receives (None: all).
        self._queues: dict[asyncio.Queue, Callable[[Event], bool] | None] = {}
        # The event loop only holds weak references to tasks, so a
        # fire-and-forget publish is kept here until it has run.
        self._pending: set[asyncio.Task] = set()

    def subscribe(self, handler: Handler) -> Handler:
        self._handlers.append(handler)
        return handler

    def unsubscribe(self, handler: Handler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def queue(
        self, maxsize: int = 500, accept: Callable[[Event], bool] | None = None
    ) -> asyncio.Queue:
        """A queue that receives every event ``accept`` lets through (all of
        them without one). A full queue drops its oldest event."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues[q] = accept
        return q

    def release(self, q: asyncio.Queue) -> None:
        self._queues.pop(q, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    async def publish(self, event: Event) -> None:
        for q, accept in list(self._queues.items()):
            if accept is not None and not accept(event):
                continue
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
        task = loop.create_task(self.publish(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)


class ServerBus(EventBus):
    """One server's handle on the shared bus.

    Managers that belong to one server publish through this, so every event
    they raise carries that server's id without each call site having to
    remember it. Subscribing and queues go straight to the shared bus.
    """

    def __init__(self, root: EventBus, server_id: str):
        # Deliberately not calling EventBus.__init__: this object has no
        # subscribers or queues of its own, every call goes to the root.
        self.root = root
        self.server_id = server_id

    def _tag(self, event: Event) -> Event:
        if event.server_id is None:
            event.server_id = self.server_id
        return event

    async def publish(self, event: Event) -> None:
        await self.root.publish(self._tag(event))

    def publish_soon(self, event: Event) -> None:
        self.root.publish_soon(self._tag(event))

    def subscribe(self, handler: Handler) -> Handler:
        return self.root.subscribe(handler)

    def unsubscribe(self, handler: Handler) -> None:
        self.root.unsubscribe(handler)

    def queue(
        self, maxsize: int = 500, accept: Callable[[Event], bool] | None = None
    ) -> asyncio.Queue:
        return self.root.queue(maxsize, accept)

    def release(self, q: asyncio.Queue) -> None:
        self.root.release(q)

    @property
    def subscriber_count(self) -> int:
        return self.root.subscriber_count
