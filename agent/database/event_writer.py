"""Writes bus events to SQLite in batches, off the event loop.

Publishing an event only appends it to a list. A background task writes
whatever has collected, in one transaction, in a worker thread, so a burst of
events (a crash, a busy console) never blocks the agent on disk I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

log = logging.getLogger("msc.events")


class EventWriter:
    INTERVAL = 1.0   # seconds between writes while events are arriving
    MAX_BATCH = 200  # write early once this many are waiting

    def __init__(self, db):
        self.db = db
        self._pending: list[dict[str, Any]] = []
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def add(self, server_id: str, type_: str, message: str, level: str = "info",
            data: dict | None = None) -> None:
        self._pending.append({
            "server_id": server_id, "ts": time.time(), "type": type_, "level": level,
            "message": message, "data": json.dumps(data) if data else None,
        })
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="event-writer")
        if len(self._pending) >= self.MAX_BATCH:
            self._wake.set()

    async def flush(self) -> None:
        """Write everything waiting now. Safe to call at any time."""
        async with self._lock:
            rows, self._pending = self._pending, []
            if not rows:
                return
            try:
                await asyncio.to_thread(self.db.add_events, rows)
            except Exception:
                log.exception("could not write %d event(s)", len(rows))

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self.INTERVAL)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            await self.flush()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush()
