"""Dashboard-editable settings, maintenance mode and notifications."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...config import ConfigError
from ...security.auth import Principal
from ...security.permissions import SETTINGS_EDIT, SETTINGS_VIEW, require
from ..deps import audit, get_core
from ..responses import AlertHistory
from .models import MaintenanceRequest, SettingsRequest

router = APIRouter()


SETTABLE_PREFIXES = (
    "monitor.",
    "thresholds.",
    "notifications.events.",
    "notifications.discord_enabled",
    "notifications.email_enabled",
    "notifications.push_enabled",
    "notifications.email.",
    "notifications.min_interval_seconds",
    "backups.keep_",
    "backups.include",
    "backups.stop_server_for_backup",
    "mods.backup_before_install",
    "mods.update_check_hours",
    "maintenance.",
    "server.max_players",
    "server.stop_timeout",
    "server.start_timeout",
    "server.autostart_minecraft",
    "server.jvm_args",
    "security.session_hours",
    "power.keep_awake",
    "updates.check",
)


@router.get("/settings")
async def get_settings(
    principal: Principal = Depends(require(SETTINGS_VIEW)), core=Depends(get_core)
):
    config = core.config.as_dict(redact_secrets=True)
    if principal.servers is not None:
        # A helper limited to some servers isn't shown the others.
        config["servers"] = [
            s for s in config.get("servers", []) if s.get("id") in principal.servers
        ]
    return {
        "config": config,
        "editable": list(SETTABLE_PREFIXES),
        "secrets": {
            "discord_webhook_configured": bool(core.config.discord_webhook),
            "smtp_configured": bool(core.config.smtp_password),
            "api_token_configured": bool(core.config.api_token),
        },
    }


@router.put("/settings")
async def update_settings(
    payload: SettingsRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    applied, rejected = {}, {}
    for key, value in payload.updates.items():
        if not any(key == p or key.startswith(p) for p in SETTABLE_PREFIXES):
            rejected[key] = "This setting cannot be changed from the dashboard"
            continue
        previous = core.config.get(key)
        core.config.set(key, value)
        try:
            core.config.section(key.split(".", 1)[0])
        except ConfigError as exc:
            core.config.set(key, previous)
            rejected[key] = str(exc)
            continue
        applied[key] = value
    if applied:
        try:
            core.config.save()
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Settings could not be written to disk: {exc}"
            ) from exc
        audit(core, request, "settings_update", detail=", ".join(applied))
    return {"ok": True, "applied": applied, "rejected": rejected}


@router.post("/maintenance")
async def set_maintenance(
    payload: MaintenanceRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    result = core.set_maintenance(payload.enabled, user=principal.user)
    audit(core, request, "maintenance_mode", detail="on" if payload.enabled else "off")
    return {"ok": True, **result}


@router.post("/notifications/test")
async def test_notification(
    channel: str,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    try:
        result = await core.notifier.test(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "notification_test", target=channel, detail=str(result["sent"]))
    return result


@router.get("/notifications/history", response_model=AlertHistory)
async def notification_history(
    limit: int = 50, principal: Principal = Depends(require(SETTINGS_VIEW)), core=Depends(get_core)
):
    return {"history": core.notifier.history(max(1, min(limit, 200)))}
