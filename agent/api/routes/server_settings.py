"""One server's own settings: its name, memory flags, timeouts, and its
overrides of the crash-handling, backup and mod settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...config import SERVER_OVERRIDES, ConfigError
from ...security.auth import Principal
from ...security.permissions import SETTINGS_EDIT, SETTINGS_VIEW, require
from ..deps import audit, get_server
from .models import ServerSettingsRequest

router = APIRouter()

SERVER_SETTABLE = (
    "server.name",
    "server.max_players",
    "server.stop_timeout",
    "server.start_timeout",
    "server.autostart_minecraft",
    "server.jvm_args",
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
        **{name: ctx.config.section(name).to_dict() for name in SERVER_OVERRIDES},
        "overrides": {
            name: ctx.config.root.server_entry(ctx.server_id).get(name) or {}
            for name in SERVER_OVERRIDES
        },
        "editable": list(SERVER_SETTABLE),
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
        audit(ctx, request, "server_settings_update", detail=", ".join(applied))
    return {"ok": True, "applied": applied, "rejected": rejected}
