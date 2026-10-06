"""Long operations as jobs the dashboard can follow.

Backups, restores and (in later phases) downloads, version changes, imports
and duplication run as jobs. The rules are the same as for the installer's
progress bar:

  * progress only moves for work that has actually been done, counted in
    real units (files written, bytes copied)
  * a step that cannot say how far along it is reports its progress as
    unknown (``total`` is None), never as an invented percentage
  * a job is "succeeded" only after its own checks have passed

A server runs one risky job at a time: a second backup, or a backup in the
middle of a restore, is refused with a message naming what is running. Jobs
are stored in the database, so a page reload (or another device) sees them,
and a job that was running when the agent stopped is marked interrupted on
the next start rather than shown as still running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .events import Event, EventBus

log = logging.getLogger("msc.jobs")

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
INTERRUPTED = "interrupted"

# Progress events are sent at most this often while a step reports work.
PUBLISH_INTERVAL = 0.5


class JobError(RuntimeError):
    pass


class JobConflict(JobError):
    """Another risky job is already running on this server."""


class JobNotFound(JobError):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    server_id: str | None = None
    risky: bool = False
    state: str = RUNNING
    step: str | None = None
    done: float | None = None
    total: float | None = None  # None while the step cannot say how much work there is
    unit: str | None = None
    message: str | None = None
    result: dict[str, Any] | None = None
    user: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def progress(self) -> float | None:
        """Fraction of the current step done, or None when unknown."""
        if self.total is None or self.done is None or self.total <= 0:
            return None
        return max(0.0, min(1.0, self.done / self.total))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["progress"] = self.progress
        return data

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Job:
        row = dict(row)
        row["risky"] = bool(row.get("risky"))
        result = row.get("result")
        row["result"] = json.loads(result) if result else None
        return cls(**row)


class JobHandle:
    """What a running job uses to report what it is doing.

    ``advance`` may be called from a worker thread (a zip being written in
    ``asyncio.to_thread``); updates are handed to the event loop.
    """

    def __init__(self, tracker: JobTracker, job: Job, loop: asyncio.AbstractEventLoop):
        self._tracker = tracker
        self.job = job
        self._loop = loop
        self._lock = threading.Lock()
        self._last_publish = 0.0

    @property
    def id(self) -> str:
        return self.job.id

    def step(self, name: str, total: float | None = None, unit: str | None = None) -> None:
        """Start a new step. ``total`` is the amount of work it will do, in
        ``unit``; leave it None when that is not known."""
        with self._lock:
            self.job.step = name
            self.job.total = total
            self.job.done = 0.0 if total is not None else None
            self.job.unit = unit
        self._changed(force=True)

    def set_total(self, total: float, unit: str | None = None) -> None:
        """The step has found out how much work there is."""
        with self._lock:
            self.job.total = total
            self.job.done = self.job.done or 0.0
            if unit:
                self.job.unit = unit
        self._changed(force=True)

    def advance(self, amount: float = 1) -> None:
        """Record work actually done."""
        with self._lock:
            if self.job.total is None:
                return  # unknown progress stays unknown
            self.job.done = min(self.job.total, (self.job.done or 0.0) + amount)
        self._changed()

    def _changed(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < PUBLISH_INTERVAL:
            return
        self._last_publish = now
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._tracker._touch(self.job)
        else:
            self._loop.call_soon_threadsafe(self._tracker._touch, self.job)


JobFunc = Callable[[JobHandle], Awaitable[Any]]


class JobTracker:
    def __init__(self, db, bus: EventBus):
        self.db = db
        self.bus = bus
        self._running: dict[str, Job] = {}
        self._risky: dict[str | None, str] = {}  # server_id -> running risky job id
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    def mark_interrupted(self) -> int:
        """At startup: nothing can still be running from a previous run."""
        rows = self.db.query("SELECT id FROM jobs WHERE state = ?", (RUNNING,))
        if rows:
            self.db.execute(
                "UPDATE jobs SET state = ?, message = ?, finished_at = ?, updated_at = ? "
                "WHERE state = ?",
                (
                    INTERRUPTED,
                    "The agent stopped before this finished.",
                    time.time(),
                    time.time(),
                    RUNNING,
                ),
            )
        return len(rows)

    def risky_job(self, server_id: str | None) -> Job | None:
        job_id = self._risky.get(server_id)
        return self._running.get(job_id) if job_id else None

    def get(self, job_id: str) -> Job:
        live = self._running.get(job_id)
        if live:
            return live
        row = self.db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise JobNotFound("That job isn't on the list any more.")
        return Job.from_row(row)

    def recent(
        self, server_id: str | None = None, limit: int = 50, running_only: bool = False
    ) -> list[Job]:
        clauses, params = [], []
        if server_id is not None:
            clauses.append("server_id = ?")
            params.append(server_id)
        if running_only:
            clauses.append("state = ?")
            params.append(RUNNING)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", (*params, limit)
        )
        jobs = []
        for row in rows:
            live = self._running.get(row["id"])
            jobs.append(live or Job.from_row(row))
        return jobs

    # ------------------------------------------------------------------
    def _save(self, job: Job) -> None:
        values = job.to_dict()
        values.pop("progress")
        values["risky"] = 1 if job.risky else 0
        values["result"] = json.dumps(job.result, default=str) if job.result is not None else None
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        updates = ", ".join(f"{k}=excluded.{k}" for k in values if k != "id")
        self.db.execute(
            f"INSERT INTO jobs ({cols}) VALUES ({marks}) ON CONFLICT(id) DO UPDATE SET {updates}",
            list(values.values()),
        )

    def _touch(self, job: Job) -> None:
        if job.state != RUNNING:
            return  # a late progress update; the job's last event has gone out
        job.updated_at = time.time()
        try:
            self._save(job)
        except Exception:  # pragma: no cover - progress must never break the job
            log.exception("could not record job progress")
        self.bus.publish_soon(self._event(job))

    def _event(self, job: Job) -> Event:
        level = {SUCCEEDED: "success", FAILED: "error", INTERRUPTED: "warn"}.get(job.state, "info")
        return Event(
            type="job",
            level=level,
            message=f"{job.title}: {job.message or job.step or job.state}",
            data=job.to_dict(),
            server_id=job.server_id,
        )

    def _begin(
        self, kind: str, title: str, server_id: str | None, risky: bool, user: str | None
    ) -> Job:
        if risky:
            current = self.risky_job(server_id)
            if current:
                raise JobConflict(
                    f"Wait for '{current.title}' to finish first. A server runs one "
                    "change like this at a time."
                )
        job = Job(
            id=uuid.uuid4().hex[:16],
            kind=kind,
            title=title,
            server_id=server_id,
            risky=risky,
            user=user,
        )
        self._running[job.id] = job
        if risky:
            self._risky[server_id] = job.id
        self._save(job)
        return job

    async def _execute(self, job: Job, func: JobFunc) -> Any:
        handle = JobHandle(self, job, asyncio.get_running_loop())
        await self.bus.publish(self._event(job))
        try:
            result = await func(handle)
        except BaseException as exc:
            job.state = FAILED if not isinstance(exc, asyncio.CancelledError) else INTERRUPTED
            job.message = str(exc) or type(exc).__name__
            raise
        else:
            job.state = SUCCEEDED
            if isinstance(result, dict):
                job.result = result
            job.message = job.message or "Done"
            return result
        finally:
            job.finished_at = job.updated_at = time.time()
            self._running.pop(job.id, None)
            if self._risky.get(job.server_id) == job.id:
                self._risky.pop(job.server_id, None)
            try:
                self._save(job)
            except Exception:  # pragma: no cover
                log.exception("could not record the end of job %s", job.id)
            await self.bus.publish(self._event(job))

    async def run(
        self,
        kind: str,
        title: str,
        func: JobFunc,
        server_id: str | None = None,
        risky: bool = False,
        user: str | None = None,
    ) -> tuple[Job, Any]:
        """Run a job and wait for it. Its exception, if any, is re-raised."""
        job = self._begin(kind, title, server_id, risky, user)
        result = await self._execute(job, func)
        return job, result

    def start(
        self,
        kind: str,
        title: str,
        func: JobFunc,
        server_id: str | None = None,
        risky: bool = False,
        user: str | None = None,
    ) -> Job:
        """Start a job in the background and return it at once."""
        job = self._begin(kind, title, server_id, risky, user)

        async def runner() -> None:
            try:
                await self._execute(job, func)
            except Exception:
                log.info("job %s (%s) failed", job.id, job.title, exc_info=True)

        task = asyncio.get_running_loop().create_task(runner(), name=f"job-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
