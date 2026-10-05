"""The Game settings page: one server's server.properties, edited safely.

Saving goes through the safe-change routine and the job tracker, like every
other risky change:

  1. every value is checked first (agent/minecraft/properties.py), and the
     port with the port manager; one bad value means nothing is written
  2. a verified backup of the old server.properties is taken. It is the
     change's one-click undo on the Backups page
  3. only the changed keys' lines are rewritten; comments and keys this app
     doesn't know stay exactly as they were
  4. the file is read back to check the new values are there

The server is never stopped for this. Minecraft reads server.properties
when it starts, so while it is running the page says the change takes
effect after a restart, and offers one.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .events import Event
from .minecraft import properties
from .ports import is_free
from .safechange import SafeChange, run_safe_change

if TYPE_CHECKING:
    from .core import ServerContext
    from .jobs import JobHandle


def port_problem(ctx: ServerContext, port: int) -> str | None:
    """Why this server can't use ``port``, or None. Another server on the
    list using it, or another program holding it now, both count."""
    owner = ctx.core.ports.used(exclude=ctx.server_id).get(("tcp", int(port)))
    if owner:
        return (
            f"The server '{ctx.core.servers[owner].name}' already uses port {port}. "
            "Pick another one."
        )
    current = ctx.core.ports.port_of(ctx).port
    if int(port) != current and not is_free(int(port), "tcp"):
        return f"Another program on this PC is using port {port}. Pick another one."
    return None


def waiting_for_restart(ctx: ServerContext, modified_at: float | None) -> bool:
    """True when the file was changed after the running server started, so
    what it is using now is not what the file says. Measured from the
    file's own time and the server's start time."""
    started = ctx.server.started_at
    return bool(ctx.server.running and started and modified_at and modified_at > started)


def view(ctx: ServerContext) -> dict[str, Any]:
    directory = ctx.config.server_dir
    data = properties.form_view(directory)
    return {
        **data,
        "running": ctx.server.running,
        "restart_needed": waiting_for_restart(ctx, data["modified_at"]),
    }


async def save(
    ctx: ServerContext,
    updates: dict[str, Any] | None = None,
    raw_text: str | None = None,
    user: str = "system",
) -> dict[str, Any]:
    """Save form values (``updates``) or the whole file as typed in
    Technical mode (``raw_text``). Returns what changed and the undo."""
    directory = ctx.config.server_dir
    path = directory / properties.FILENAME
    if raw_text is not None:
        edited = properties.check_raw_text(raw_text)
        before = properties.PropertiesFile.read(path).values() if path.is_file() else {}
        after = edited.values()
        port = after.get("server-port")
        if port and port.strip() != (before.get("server-port") or "").strip():
            problem = port_problem(ctx, int(port))
            if problem:
                raise properties.FormError({"server-port": problem})
        seed_before = (before.get("level-seed") or "").strip()
        seed_after = (after.get("level-seed") or "").strip()
        if seed_after != seed_before and properties.world_exists(directory, before):
            raise properties.FormError(
                {"level-seed": "The world already exists, so its seed can't change."}
            )
        changed = {
            key: value
            for key, value in after.items()
            if before.get(key) != value and key in properties.FIELDS_BY_KEY
        }
        others = sorted(
            key for key in set(after) | set(before) if before.get(key) != after.get(key)
        )
        current_text = properties.PropertiesFile.read(path).text() if path.is_file() else ""
        if edited.text() == current_text:
            return {"changed": {}, "nothing_changed": True, **_after(ctx)}
    else:
        edited, changed = properties.apply_form(
            directory, updates or {}, lambda port: port_problem(ctx, port)
        )
        others = sorted(changed)
        if not changed:
            return {"changed": {}, "nothing_changed": True, **_after(ctx)}

    async def change(job: JobHandle | None) -> dict[str, Any]:
        await asyncio.to_thread(edited.write, path)
        return {"changed": changed, "keys": others}

    async def check(result: dict[str, Any]) -> tuple[bool, str]:
        written = properties.PropertiesFile.read(path).values()
        expected = edited.values()
        wrong = [key for key, value in expected.items() if written.get(key) != value]
        if wrong:
            return False, f"{', '.join(wrong[:3])} didn't read back as saved"
        return True, f"{len(result['keys'])} setting(s) read back as saved"

    plan = SafeChange(
        title="Changing game settings",
        change=change,
        check=check,
        stop_server=False,
        take_backup=path.is_file(),
        backup_name="pre-game-settings",
        backup_note="Automatic copy of server.properties before changing game settings",
        backup_includes=[properties.FILENAME],
    )

    async def run(job: JobHandle | None) -> dict[str, Any]:
        return await run_safe_change(ctx.server, ctx.backups, plan, job=job, user=user)

    _, outcome = await ctx.core.jobs.run(
        "game_settings",
        f"Changing game settings on {ctx.name}",
        run,
        server_id=ctx.server_id,
        risky=True,
        user=user,
    )
    _follow(ctx, edited.values())
    ctx.core.db.audit(
        "game_settings",
        user=user,
        target=ctx.server_id,
        detail=", ".join(others)[:300],
        server_id=ctx.server_id,
    )
    await ctx.bus.publish(
        Event(
            type="game_settings_changed",
            level="info",
            message=(
                f"Game settings changed on {ctx.name}"
                + (". They take effect after a restart." if ctx.server.running else ".")
            ),
            data={"changed": changed, "keys": others[:20], "running": ctx.server.running},
        )
    )
    return {
        "changed": changed,
        "keys": others,
        "undo": outcome.get("undo"),
        "safety_backup": (outcome.get("safety_backup") or {}).get("name"),
        **_after(ctx),
    }


def _after(ctx: ServerContext) -> dict[str, Any]:
    path = ctx.config.server_dir / properties.FILENAME
    modified = path.stat().st_mtime if path.is_file() else None
    return {
        "running": ctx.server.running,
        "restart_needed": waiting_for_restart(ctx, modified),
    }


def _follow(ctx: ServerContext, values: dict[str, str]) -> None:
    """Keep the app's own copies of the port and player limit in step with
    the file, which is what Minecraft actually uses."""
    updates: dict[str, Any] = {}
    port = (values.get("server-port") or "").strip()
    if port.isdigit() and int(port) != ctx.config.server.port:
        updates["server.port"] = int(port)
    players = (values.get("max-players") or "").strip()
    if players.isdigit() and int(players) != ctx.config.server.max_players:
        updates["server.max_players"] = int(players)
    if not updates:
        return
    for key, value in updates.items():
        ctx.config.set(key, value)
    try:
        ctx.config.save()
    except OSError:  # pragma: no cover - the file is still right; only the copy lags
        pass
