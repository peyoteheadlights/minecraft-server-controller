"""World undo: going back to the world as it was at a point in time.

This adds no new way of storing anything. It reads the backups that already
exist, picks the ones that hold a world, and presents them as a timeline
with what going back to each one would lose. Only the world folders are put
back (mods, config and server.properties stay as they are now). The restore
itself is ``BackupManager.restore``, which verifies the archive, takes a fresh backup
of the current world first (so the undo can itself be undone) and runs
through the safe-change routine.

House rule 1 shapes "what you'd lose": the hours since a backup is
arithmetic on its timestamp, but how much of that was actually played comes
from the sessions the player tracker recorded. Where nothing was recorded,
that is reported as not known rather than as "no play".
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .minecraft.properties import world_folders

if TYPE_CHECKING:
    from .core import ServerContext

# The longest timeline shown; older backups are still on the Backups page.
LIMIT = 40


def world_parts(ctx: ServerContext) -> set[str]:
    """This server's world folders, from its level-name."""
    return world_folders(ctx.config.server_dir, ctx.config.server_type)


def _world_in(backup: dict[str, Any], parts: set[str]) -> set[str]:
    """Which of the world folders a backup holds (its top-level entries are
    recorded as a comma-separated list)."""
    includes = {p.strip() for p in (backup.get("includes") or "").split(",") if p.strip()}
    return includes & parts


def played_seconds(ctx: ServerContext, since: float, until: float) -> float | None:
    """How long anybody was playing between two moments, in seconds.

    Sessions are counted only for the part that falls inside the window, and
    overlapping sessions count once: three friends playing together for an
    hour is one hour of the world changing, not three. The result is None
    when this server has no session history at all, which is not the same as
    nobody having played.
    """
    rows = ctx.db.query(
        "SELECT joined_at, left_at FROM player_sessions WHERE server_id = ? "
        "AND (left_at IS NULL OR left_at >= ?) AND joined_at <= ?",
        (ctx.server_id, since, until),
    )
    if not rows and not ctx.db.query_one(
        "SELECT 1 AS found FROM player_sessions WHERE server_id = ? LIMIT 1", (ctx.server_id,)
    ):
        return None
    spans = sorted(
        (max(float(row["joined_at"]), since), min(float(row["left_at"] or until), until))
        for row in rows
    )
    total = 0.0
    current_start: float | None = None
    current_end = 0.0
    for start, end in spans:
        if end <= start:
            continue
        if current_start is None or start > current_end:
            if current_start is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_start is not None:
        total += current_end - current_start
    return total


def timeline(ctx: ServerContext, now: float | None = None) -> dict[str, Any]:
    """The points this server's world can be put back to, newest first."""
    now = now if now is not None else time.time()
    parts = world_parts(ctx)
    points = []
    for backup in ctx.backups.list_backups():
        if not _world_in(backup, parts) or not backup.get("exists"):
            continue
        created = float(backup["created_at"])
        points.append(
            {
                "backup_id": backup["id"],
                "name": backup["name"],
                "created_at": created,
                "age_seconds": max(0.0, now - created),
                "size_bytes": backup.get("size_bytes"),
                "kind": backup.get("kind"),
                "note": backup.get("note"),
                # Only a backup the app checked may be offered as an undo
                # point; the others are listed with why they are not.
                "checked": backup.get("status") == "ok",
                "status": backup.get("status"),
                "played_seconds": played_seconds(ctx, created, now),
                "includes": backup.get("includes"),
            }
        )
        if len(points) >= LIMIT:
            break
    running = ctx.server.running
    return {
        "points": points,
        "server_running": running,
        # The server has to be off for this: a running Minecraft holds the
        # world open and would write over whatever was put back.
        "can_restore": not running and not ctx.server.held_by,
        "blocked_by": ctx.server.held_by,
        "sessions_recorded": any(p["played_seconds"] is not None for p in points),
    }


class WorldUndoError(RuntimeError):
    """Written for people: why the world cannot be put back right now."""


async def restore(ctx: ServerContext, backup_id: int, user: str = "system") -> dict[str, Any]:
    """Put the world back to one point. The server must already be stopped.

    Unlike the Backups page, this does not stop Minecraft for you: the
    person chose a point in time, and stopping a server people are playing
    on is not part of that choice.
    """
    if ctx.server.running:
        raise WorldUndoError(
            f"Stop {ctx.name} first. The world can only be put back while the server is off."
        )
    if ctx.server.held_by:
        raise WorldUndoError(f"Wait for '{ctx.server.held_by}' to finish first.")
    point = next((p for p in timeline(ctx)["points"] if p["backup_id"] == backup_id), None)
    if point is None:
        raise WorldUndoError("That point isn't on this server's timeline any more.")
    if not point["checked"]:
        raise WorldUndoError(
            f"That backup was not checked ({point['status']}), so it is not offered as an undo."
        )
    # Only the world goes back. The backup may also hold mods, config and
    # server.properties, and putting those back would quietly undo every
    # mod or setting changed since, which "Restore world" never promised.
    result = await ctx.backups.restore(
        backup_id, user=user, start_after=False, safety_backup=True, only=world_parts(ctx)
    )
    return {**result, "point": point}
