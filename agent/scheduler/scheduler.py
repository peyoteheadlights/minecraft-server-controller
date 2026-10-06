"""Scheduled tasks.

Three schedule kinds, kept deliberately small so the next-run time is always
explainable in the UI:

  daily     expr = "23:00"
  weekly    expr = "sun 04:00"
  interval  expr = "6h" / "90m" / "45s"

Tasks: start, stop, restart, backup, log_cleanup, notify, maintenance_on,
maintenance_off. Nothing here can run an arbitrary command.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from ..events import Event, EventBus

log = logging.getLogger("msc.scheduler")

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
TIME_RE = re.compile(r"^(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)$")
WEEKLY_RE = re.compile(r"^(?P<day>mon|tue|wed|thu|fri|sat|sun)\s+(?P<time>[0-2]?\d:[0-5]\d)$", re.I)
INTERVAL_RE = re.compile(r"^(?P<n>\d+)(?P<unit>[smhd])$", re.I)

TASKS = (
    "start",
    "stop",
    "restart",
    "backup",
    "log_cleanup",
    "notify",
    "maintenance_on",
    "maintenance_off",
)


class ScheduleError(ValueError):
    pass


def next_run(kind: str, expr: str, after: float | None = None) -> float:
    now = datetime.fromtimestamp(after or time.time())
    kind = kind.lower()
    expr = expr.strip().lower()

    if kind == "daily":
        m = TIME_RE.match(expr)
        if not m:
            raise ScheduleError("A daily schedule needs a time like 23:00")
        target = now.replace(
            hour=int(m.group("h")), minute=int(m.group("m")), second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()

    if kind == "weekly":
        m = WEEKLY_RE.match(expr)
        if not m:
            raise ScheduleError("A weekly schedule needs a day and time like 'sun 04:00'")
        wanted = WEEKDAYS[m.group("day").lower()]
        hh, mm = m.group("time").split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        days_ahead = (wanted - target.weekday()) % 7
        target += timedelta(days=days_ahead)
        if target <= now:
            target += timedelta(days=7)
        return target.timestamp()

    if kind == "interval":
        m = INTERVAL_RE.match(expr)
        if not m:
            raise ScheduleError("An interval needs a value like 6h, 90m or 45s")
        seconds = (
            int(m.group("n")) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group("unit").lower()]
        )
        if seconds < 30:
            raise ScheduleError("The shortest gap between runs is 30 seconds.")
        return (now + timedelta(seconds=seconds)).timestamp()

    raise ScheduleError("Pick every day, every week, or every few hours.")


class Scheduler:
    def __init__(self, config, bus: EventBus, db, server, backups=None, notifier=None):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self.backups = backups
        self.notifier = notifier
        self._task: asyncio.Task | None = None
        self.handlers: dict[str, Callable] = {
            "start": self._task_start,
            "stop": self._task_stop,
            "restart": self._task_restart,
            "backup": self._task_backup,
            "log_cleanup": self._task_log_cleanup,
            "notify": self._task_notify,
            "maintenance_on": self._task_maintenance_on,
            "maintenance_off": self._task_maintenance_off,
        }

    # ------------------------------------------------------------------
    def list_schedules(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM schedules WHERE server_id = ? ORDER BY next_run ASC",
            (self.server.server_id,),
        )
        for row in rows:
            row["payload"] = json.loads(row.get("payload") or "{}")
            row["enabled"] = bool(row["enabled"])
        return rows

    def add(
        self,
        name: str,
        task: str,
        kind: str,
        expr: str,
        payload: dict | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        if task not in TASKS:
            raise ScheduleError(
                f"'{task}' isn't something this app can schedule. Pick one of: {', '.join(TASKS)}."
            )
        upcoming = next_run(kind, expr)
        row_id = self.db.insert(
            "schedules",
            {
                "server_id": self.server.server_id,
                "name": name[:80],
                "task": task,
                "kind": kind.lower(),
                "expr": expr.strip(),
                "payload": json.dumps(payload or {}),
                "enabled": 1 if enabled else 0,
                "next_run": upcoming,
            },
        )
        return self.get(row_id)

    def get(self, schedule_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM schedules WHERE id = ? AND server_id = ?",
            (schedule_id, self.server.server_id),
        )
        if not row:
            raise ScheduleError("That schedule isn't on the list any more.")
        row["payload"] = json.loads(row.get("payload") or "{}")
        row["enabled"] = bool(row["enabled"])
        return row

    def update(self, schedule_id: int, **changes) -> dict[str, Any]:
        row = self.get(schedule_id)
        kind = changes.get("kind", row["kind"])
        expr = changes.get("expr", row["expr"])
        task = changes.get("task", row["task"])
        if task not in TASKS:
            raise ScheduleError(f"'{task}' isn't something this app can schedule.")
        upcoming = next_run(kind, expr)
        enabled = changes.get("enabled", row["enabled"])
        self.db.execute(
            "UPDATE schedules SET name = ?, task = ?, kind = ?, expr = ?, payload = ?, "
            "enabled = ?, next_run = ? WHERE id = ?",
            (
                changes.get("name", row["name"]),
                task,
                kind,
                expr,
                json.dumps(changes.get("payload", row["payload"])),
                1 if enabled else 0,
                upcoming,
                schedule_id,
            ),
        )
        return self.get(schedule_id)

    def delete(self, schedule_id: int) -> None:
        self.get(schedule_id)
        self.db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def seed_defaults(self) -> None:
        if self.db.query_one(
            "SELECT id FROM schedules WHERE server_id = ?", (self.server.server_id,)
        ):
            return
        self.add("Nightly backup", "backup", "daily", "23:00", enabled=True)
        self.add("Weekly restart", "restart", "weekly", "sun 04:00", enabled=False)
        self.add("Log cleanup", "log_cleanup", "weekly", "mon 05:00", enabled=True)

    # ------------------------------------------------------------------
    async def _task_start(self, payload: dict) -> str:
        from ..minecraft.process import ServerError

        try:
            await self.server.start(actor="scheduler")
            return "Server start requested"
        except ServerError as exc:
            return f"Skipped: {exc}"

    async def _task_stop(self, payload: dict) -> str:
        from ..minecraft.process import ServerError
        from ..minecraft.state import ExitReason

        warn = payload.get("warn_seconds", 60)
        try:
            if self.server.state.value == "ONLINE" and warn:
                await self.server.send_command(
                    f"say Server stopping in {int(warn)} seconds", internal=True
                )
                await asyncio.sleep(float(warn))
            await self.server.stop(actor="scheduler", reason=ExitReason.SCHEDULED_STOP)
            return "Server stopped"
        except ServerError as exc:
            return f"Skipped: {exc}"

    async def _task_restart(self, payload: dict) -> str:
        warn = payload.get("warn_seconds", 60)
        if self.server.state.value == "ONLINE" and warn:
            try:
                await self.server.send_command(
                    f"say Server restarting in {int(warn)} seconds", internal=True
                )
                await asyncio.sleep(float(warn))
            except Exception:
                pass
        await self.server.restart(actor="scheduler")
        return "Server restarted"

    async def _task_backup(self, payload: dict) -> str:
        if not self.backups:
            return "No backup manager is available"
        result = await self.backups.create(kind=payload.get("kind", "scheduled"), user="scheduler")
        return f"Created {result['name']} ({result['size_bytes'] / 1024**3:.2f} GB)"

    async def _task_log_cleanup(self, payload: dict) -> str:
        days = int(payload.get("days", 30))
        cutoff = time.time() - days * 86400
        removed = 0
        for folder in (self.config.server_dir / "logs", self.config.log_dir):
            if not folder.is_dir():
                continue
            for file in folder.iterdir():
                if not file.is_file() or file.is_symlink():
                    continue
                if file.name in ("latest.log", "agent.log"):
                    continue
                if file.suffix.lower() not in (".gz", ".log", ".txt"):
                    continue
                if file.stat().st_mtime < cutoff:
                    file.unlink(missing_ok=True)
                    removed += 1
        self.db.prune(metrics_days=self.config.monitor.history_days)
        return f"Removed {removed} old log file(s) and pruned old metrics"

    async def _task_notify(self, payload: dict) -> str:
        await self.bus.publish(
            Event(
                type="server_started" if payload.get("as") == "started" else "maintenance_mode",
                message=payload.get("message", "Scheduled notification"),
                level="info",
            )
        )
        return "Notification published"

    async def _task_maintenance_on(self, payload: dict) -> str:
        self.server.maintenance = True
        await self.bus.publish(
            Event(type="maintenance_mode", level="warn", message="Maintenance mode on (scheduled)")
        )
        return "Maintenance mode on"

    async def _task_maintenance_off(self, payload: dict) -> str:
        self.server.maintenance = False
        await self.bus.publish(
            Event(type="maintenance_mode", level="info", message="Maintenance mode off (scheduled)")
        )
        return "Maintenance mode off"

    # ------------------------------------------------------------------
    async def run_task(self, row: dict[str, Any]) -> str:
        handler = self.handlers.get(row["task"])
        if not handler:
            return f"Unknown task '{row['task']}'"
        return await handler(row.get("payload") or {})

    async def run_due(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        results = []
        blocked = self.server.maintenance and self.config.maintenance.block_scheduled_tasks
        for row in self.list_schedules():
            if not row["enabled"] or not row.get("next_run") or row["next_run"] > now:
                continue
            if blocked and row["task"] not in ("maintenance_off", "notify"):
                self.db.execute(
                    "UPDATE schedules SET next_run = ?, last_result = ? WHERE id = ?",
                    (
                        next_run(row["kind"], row["expr"], now),
                        "Skipped: maintenance mode",
                        row["id"],
                    ),
                )
                continue
            await self.bus.publish(
                Event(type="schedule_running", message=f"Running scheduled task: {row['name']}")
            )
            try:
                result = await self.run_task(row)
                level = "info"
            except Exception as exc:
                log.exception("scheduled task failed: %s", row["name"])
                result, level = f"Failed: {exc}", "error"
            self.db.execute(
                "UPDATE schedules SET last_run = ?, next_run = ?, last_result = ? WHERE id = ?",
                (now, next_run(row["kind"], row["expr"], now), result[:300], row["id"]),
            )
            self.db.add_event(
                self.server.server_id, "schedule", f"{row['name']}: {result}", level=level
            )
            await self.bus.publish(
                Event(type="schedule_finished", level=level, message=f"{row['name']}: {result}")
            )
            results.append({"id": row["id"], "name": row["name"], "result": result})
        return results

    async def run(self) -> None:
        while True:
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                log.exception("scheduler loop error")
            await asyncio.sleep(20)

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self.run(), name="scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
