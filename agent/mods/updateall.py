"""Update all: every ticked mod or plugin updated as one change.

The server has to be stopped already (as for a single update). One backup
of the mods or plugins folder is made and checked first, then each mod is
updated in turn with the same step a single update uses. If any of them
fails, the whole folder is put back from that backup, so a server is never
left with half its mods updated, and the answer names the one that failed.
Being one change, it has one backup and one Undo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..jobs import JobConflict
from ..safechange import SafeChange, run_safe_change
from .manager import ModError

if TYPE_CHECKING:
    from ..core import ServerContext
    from ..jobs import JobHandle

TITLE = "Update all"


async def update_all(
    ctx: ServerContext, wanted: list[dict[str, Any]], user: str = "system"
) -> dict[str, Any]:
    """Update each of ``wanted`` (``filename`` and an optional
    ``version_id``). Raises before anything changes when the server runs,
    another task holds it, or a file isn't in the folder."""
    mods = ctx.mods
    ctx.require_free()
    mods._require_server_offline(f"update {mods.word}s")
    # The same file twice would fail the second time (it was renamed by the first).
    unique: dict[str, dict[str, Any]] = {}
    for item in wanted:
        unique.setdefault(item["filename"], item)
    targets = [(mods.find(item["filename"]), item.get("version_id")) for item in unique.values()]
    # What the agent notes about each mod (where it came from, its update),
    # put back with the files if one update fails.
    noted = [f"mod_{kind}:{mod.mod_id}" for mod, _ in targets for kind in ("source", "update")]
    try:
        folder = ctx.config.mods_dir.resolve().relative_to(ctx.config.server_dir.resolve()).parts[0]
    except (ValueError, IndexError):
        # A backup holds only what is inside the server folder, so it
        # couldn't put these mods back if one update failed.
        raise ModError(
            f"Update all needs the {mods.server_type.content} folder inside the server folder. "
            f"Update each {mods.word} on its own instead."
        ) from None

    async def change(job: JobHandle | None) -> dict[str, Any]:
        before = {key: mods.db.get_setting(key) for key in noted}
        updated = []
        for number, (mod, version_id) in enumerate(targets, start=1):
            if job:
                job.step(f"Updating {mod.name} ({number} of {len(targets)})")
            try:
                result = await mods.update(mod.filename, user=user, version_id=version_id)
                if not mod.enabled:
                    # A turned-off mod is updated, and stays off.
                    await mods.set_enabled(result["updated"]["filename"], False, user=user)
            except Exception as exc:
                for key, value in before.items():
                    mods.db.set_setting(key, value)
                raise ModError(f"Updating {mod.name} failed: {exc}") from exc
            updated.append(
                {
                    "mod_id": mod.mod_id,
                    "name": mod.name,
                    "filename": result["updated"]["filename"],
                    "previous_version": mod.version,
                    "version": result["updated"]["version"],
                }
            )
        return {"updated": updated}

    plan = SafeChange(
        title=TITLE,
        change=change,
        stop_server=True,  # already stopped; this holds it so nothing starts it meanwhile
        take_backup=True,
        backup_name="before-update-all",
        backup_note=f"Before {TITLE}",
        backup_includes=[folder],
    )

    async def run(job: JobHandle | None) -> dict[str, Any]:
        # Asked again just before: it may have been started while this waited
        # its turn, and Update all never stops a running server.
        mods._require_server_offline(f"update {mods.word}s")
        return await run_safe_change(ctx.server, ctx.backups, plan, job=job, user=user)

    names = ", ".join(mod.name for mod, _ in targets)
    try:
        job, outcome = await ctx.core.jobs.run(
            "mods", f"{TITLE} on {ctx.name}", run, server_id=ctx.server_id, risky=True, user=user
        )
    except JobConflict:
        raise
    except Exception as exc:
        mods.record("update_all", user, result="failed", detail=str(exc)[:500])
        raise
    mods.record("update_all", user, detail=names[:500])
    return {
        "job_id": job.id,
        "updated": outcome["updated"],
        "safety_backup": outcome["safety_backup"],
        "undo": outcome["undo"],
    }
