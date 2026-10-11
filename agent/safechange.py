"""The safe-change routine: one way to make any risky change to a server.

    1. stop the server if the change needs it
    2. take a backup and verify it (a change never starts without one)
    3. make the change
    4. check the result
    5. if the change or the check fails, put the backup back
    6. start the server again if asked

The backup taken in step 2 is the change's undo: a change that succeeds goes
on the server's undo stack (agent/changes.py), and Undo puts that backup back.
Restores, game settings, world and modpack imports, version and type changes
and duplication all run through this routine.
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
    # What a successful change does to Undo and Redo: "push" puts it on the
    # undo stack; "clear_redo" is a change Undo can't reverse (a version
    # change, which has its own Roll back), so it only empties Redo; "none"
    # is Undo and Redo themselves, or a change that leaves this server as it
    # was (duplicating it).
    history: str = "push"
    # What Undo puts back: these top-level names, or (None) what the backup
    # holds.
    undo_scope: list[str] | None = None


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

    change_id = _record(backups, change, safety, job, user)

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
        if safety and change.history == "push"
        else None,
        "change_id": change_id,
        "check": detail,
        "was_running": was_running,
        "server_started": started,
    }


def _record(
    backups: BackupManager,
    change: SafeChange,
    safety: dict[str, Any] | None,
    job: JobHandle | None,
    user: str,
) -> int | None:
    """Put a finished change on the undo stack, or just empty Redo."""
    history = getattr(backups, "changes", None)
    if history is None or change.history == "none":
        return None
    if change.history != "push" or not safety:
        history.clear_redo()
        return None
    scope = change.undo_scope if change.undo_scope is not None else change.backup_includes
    return history.push(change.title, safety["id"], scope, user, job_id=job.id if job else None)


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
            note=change.backup_note or before(change.title),
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


def before(title: str) -> str:
    """The note on a backup made before a change, which is also how the
    Backups list labels it: "Before changing game settings"."""
    return f"Before {title[:1].lower()}{title[1:]}"


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
            f" Putting the previous files back also failed ({exc}); the backup "
            f"{safety['name']} is still there to restore."
        )
    return f" The previous files were put back from the backup {safety['name']}."
