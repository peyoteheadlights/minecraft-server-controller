"""One server's own settings: its name, memory flags, timeouts, and its
overrides of the crash-handling, backup and mod settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import colors
from ...config import SERVER_OVERRIDES, ConfigError
from ...events import Event
from ...minecraft import cpu
from ...security.auth import Principal
from ...security.permissions import SETTINGS_EDIT, SETTINGS_VIEW, require
from ..deps import audit, get_server
from .models import ServerColorRequest, ServerSettingsRequest

router = APIRouter()

SERVER_SETTABLE = (
    "server.name",
    "server.max_players",
    "server.stop_timeout",
    "server.start_timeout",
    "server.autostart_minecraft",
    "server.jvm_args",
    "server.cpu_cores",
    "monitor.",
    "backups.keep_",
    "backups.include",
    "backups.stop_server_for_backup",
    "mods.backup_before_install",
    "mods.update_check_hours",
)


@router.get("/settings")
async def get_server_settings(
    principal: Principal = Depends(require(SETTINGS_VIEW)), ctx=Depends(get_server)
):
    return {
        "server_id": ctx.server_id,
        "server": ctx.config.server.to_dict(),
        "color": ctx.color,
        "palette": colors.palette(),
        **{name: ctx.config.section(name).to_dict() for name in SERVER_OVERRIDES},
        "overrides": {
            name: ctx.config.root.server_entry(ctx.server_id).get(name) or {}
            for name in SERVER_OVERRIDES
        },
        "editable": list(SERVER_SETTABLE),
        "cpu": _cpu_overview(ctx),
    }


def _cpu_overview(ctx) -> dict:
    """What the CPU core picker needs: this PC's cores, whether limits work
    here, and which cores every other server is set to use."""
    supported, why = cpu.supported()
    others = []
    for other in ctx.core.servers.values():
        if other is ctx:
            continue
        others.append(
            {"id": other.server_id, "name": other.name, "cores": other.config.server.cpu_cores}
        )
    return {
        "logical_cores": cpu.logical_cores(),
        "supported": supported,
        "unsupported_reason": why,
        "others": others,
        "status": cpu.status(
            ctx.server.pid if ctx.server.running else None, ctx.config.server.cpu_cores
        ),
    }


@router.put("/settings")
async def update_server_settings(
    payload: ServerSettingsRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    applied, rejected = {}, {}
    for key, value in payload.updates.items():
        if not any(key == p or key.startswith(p) for p in SERVER_SETTABLE):
            rejected[key] = "This setting cannot be changed from the dashboard"
            continue
        if key == "server.cpu_cores":
            found = cpu.shape_problems(value) or cpu.problems(value)
            if found:
                rejected[key] = found[0]
                continue
        previous = ctx.config.get(key)
        ctx.config.set(key, value)
        try:
            ctx.config.section(key.split(".", 1)[0])
        except ConfigError as exc:
            ctx.config.set(key, previous)
            rejected[key] = str(exc)
            continue
        applied[key] = value
    if applied:
        try:
            ctx.config.save()
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Settings could not be written to disk: {exc}"
            ) from exc
        if "server.name" in applied:
            ctx.core.db.register_server(
                ctx.server_id, ctx.config.server.name, str(ctx.config.server_dir)
            )
            await _announce_change(ctx, f"Renamed the server to {ctx.name}")
        audit(ctx, request, "server_settings_update", detail=", ".join(applied))
    result: dict = {"ok": True, "applied": applied, "rejected": rejected}
    if "server.cpu_cores" in applied and ctx.server.running:
        # Applied to the running server at once, and read back from it.
        result["cpu_cores"] = await ctx.server.apply_cpu_cores()
    return result


@router.put("/color")
async def set_color(
    payload: ServerColorRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Set this server's color: a palette color or the person's own hex."""
    try:
        color = colors.normalise(payload.color)
    except colors.ColorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ctx.core.db.set_server_color(ctx.server_id, color)
    audit(ctx, request, "server_color", detail=color)
    await _announce_change(ctx, f"Changed {ctx.name}'s color")
    return {"ok": True, "color": color}


async def _announce_change(ctx, message: str) -> None:
    """Tells every open dashboard to reload the server list (name, color)."""
    await ctx.bus.publish(
        Event(type="server_changed", message=message, data={"color": ctx.color, "name": ctx.name})
    )
