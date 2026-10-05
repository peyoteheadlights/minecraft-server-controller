"""The safe-change routine: one way to make any risky change to a server.

    1. stop the server if the change needs it
    2. take a backup and verify it (a change never starts without one)
    3. make the change
    4. check the result
    5. if the change or the check fails, put the backup back
    6. start the server again if asked

The backup taken in step 2 is the change's one-click undo: the job's result
records it, and undoing restores it (through this same routine, so the undo
can itself be undone). Restoring a backup uses this routine today; version
and type changes, world import, modpack import, duplication and settings
edits in later phases will too.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .events import Event

if TYPE_CHECKING:
    from .backups.manager import BackupManager
    from .jobs import JobHandle
    from .minecraft.process import MinecraftServer

log = logging.getLogger("msc.safechange")

CheckResult = tuple[bool, str]


class SafeChangeError(RuntimeError):
    pass


@dataclass
class SafeChange:
    title: str  # what the change does, e.g. "Restore manual-20261005.zip"
    change: Callable[[JobHandle | None], Awaitable[dict[str, Any]]]
    # Returns (ok, detail). None means the change checks itself.
    check: Callable[[dict[str, Any]], Awaitable[CheckResult]] | None = None
    stop_server: bool = True
    start_after: bool = False
    take_backup: bool = True
    backup_name: str = "pre-change"
    backup_note: str | None = None
    backup_includes: list[str] | None = field(default=None)
    # False when the change already puts things back itself if it fails part
    # way (restoring a backup does), so the safety backup is not extracted
    # over files that are already back as they were.
    undo_on_change_error: bool = True


async def run_safe_change(
    server: MinecraftServer,
    backups: BackupManager,
    change: SafeChange,
    job: JobHandle | None = None,
    user: str = "system",
) -> dict[str, Any]:
    """Run ``change`` with a verified backup behind it. Returns what the
    change returned plus ``safety_backup``, ``undo`` and ``check``."""
    from .minecraft.process import ServerError

    def step(name: str) -> None:
        if job:
            job.step(name)

    was_running = server.running
    if change.stop_server and server.held_by:
        raise SafeChangeError(f"Wait for '{server.held_by}' to finish first")
    if change.stop_server:
        # Held from before the stop until the result is checked, so nothing
        # (a click, a schedule, another device) starts Minecraft on files
        # that are half changed.
        server.held_by = change.title
    try:
        result, detail, safety = await _change_held(server, backups, change, job, user, was_running)
    finally:
        if change.stop_server:
            server.held_by = None

    started = False
    if change.start_after:
        step("Starting the server")
        try:
            await server.start(actor=user)
            started = await server.wait_online()
        except ServerError as exc:
            await server.bus.publish(
                Event(
                    type="restore_start_failed",
                    level="error",
                    message=f"The server did not start after the change: {exc}",
                )
            )
    return {
        **result,
        "safety_backup": safety,
        "undo": {"kind": "restore_backup", "backup_id": safety["id"], "backup": safety["name"]}
        if safety
        else None,
        "check": detail,
        "was_running": was_running,
        "server_started": started,
    }


async def _change_held(
    server: MinecraftServer,
    backups: BackupManager,
    change: SafeChange,
    job: JobHandle | None,
    user: str,
    was_running: bool,
) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    """Steps 1 to 5: stop, back up, change, check, undo on failure."""
    from .minecraft.state import ExitReason

    def step(name: str) -> None:
        if job:
            job.step(name)

    if change.stop_server and was_running:
        step("Stopping the server")
        await server.bus.publish(
            Event(type="restore_stopping", message=f"Stopping the server for: {change.title}")
        )
        await server.stop(actor=user, reason=ExitReason.USER_STOP)

    safety: dict[str, Any] | None = None
    if change.take_backup:
        # create() raises if the backup fails or does not verify, and then
        # nothing below has happened.
        safety = await backups.create(
            name=change.backup_name,
            kind="safety",
            includes=change.backup_includes,
            user=user,
            note=change.backup_note or f"Automatic safety copy before: {change.title}",
            job=job,
        )

    step(change.title)
    try:
        result = await change.change(job)
    except Exception as exc:
        undone = await _undo(backups, safety, job) if change.undo_on_change_error else ""
        raise SafeChangeError(f"{exc}{undone}") from exc

    detail = ""
    if change.check:
        step("Checking the result")
        ok, detail = await change.check(result)
        if not ok:
            undone = await _undo(backups, safety, job)
            raise SafeChangeError(f"The result could not be verified: {detail}{undone}")
    return result, detail, safety


async def _undo(
    backups: BackupManager, safety: dict[str, Any] | None, job: JobHandle | None
) -> str:
    """Put the safety backup back after a failed change. Returns a sentence
    for the error message saying what happened."""
    if not safety:
        return ""
    if job:
        job.step("Putting the previous files back")
    try:
        await backups.put_back(safety["id"])
    except Exception as exc:  # pragma: no cover - reported, never hidden
        log.exception("could not put the safety backup back")
        return (
            f" Putting the previous files back also failed ({exc}); the safety backup "
            f"{safety['name']} is still there to restore."
        )
    return f" The previous files were put back from the safety backup {safety['name']}."
