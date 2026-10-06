"""World undo: going back to the world as it was at a point in time.

This adds no new way of storing anything. It reads the backups that already
exist, picks the ones that hold a world, and presents them as a timeline
with what going back to each one would lose. The restore itself is
``BackupManager.restore``, which verifies the archive, takes a fresh backup
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

if TYPE_CHECKING:
    from .core import ServerContext

# A backup counts for the timeline when it holds at least one of these.
WORLD_FOLDERS = ("world", "world_nether", "world_the_end")
# The longest timeline shown; older backups are still on the Backups page.
LIMIT = 40


def _holds_world(backup: dict[str, Any]) -> bool:
    includes = backup.get("includes") or ""
    return any(folder in includes for folder in WORLD_FOLDERS)


def played_seconds(ctx: ServerContext, since: float, until: float) -> float | None:
    """How much play the tracker recorded between two moments, in seconds.

    Sessions are counted only for the part that falls inside the window. The
    result is None when this server has no session history at all, which is
    not the same as nobody having played.
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
    total = 0.0
    for row in rows:
        start = max(float(row["joined_at"]), since)
        end = min(float(row["left_at"] or until), until)
        if end > start:
            total += end - start
    return total


def timeline(ctx: ServerContext, now: float | None = None) -> dict[str, Any]:
    """The points this server's world can be put back to, newest first."""
    now = now if now is not None else time.time()
    points = []
    for backup in ctx.backups.list_backups():
        if not _holds_world(backup) or not backup.get("exists"):
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
    result = await ctx.backups.restore(backup_id, user=user, start_after=False, safety_backup=True)
    return {**result, "point": point}
