"""Creating, verifying, downloading, restoring and deleting backups."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from ...security.auth import Principal
from ...security.permissions import (
    BACKUPS_CREATE,
    BACKUPS_DELETE,
    BACKUPS_DOWNLOAD,
    BACKUPS_RESTORE,
    SERVER_VIEW,
    require,
)
from ..deps import get_server
from ..errors import audit_failure, respond_as
from .models import BackupRequest, RestoreRequest

router = APIRouter()


@router.get("/backups")
async def list_backups(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return {
        "backups": ctx.backups.list_backups(),
        "directory": str(ctx.config.backup_dir),
        "retention": {
            "daily": ctx.config.backups.keep_daily,
            "weekly": ctx.config.backups.keep_weekly,
            "monthly": ctx.config.backups.keep_monthly,
        },
    }


@router.post("/backups")
async def create_backup(
    payload: BackupRequest,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_CREATE)),
    ctx=Depends(get_server),
):
    with audit_failure(ctx, request, "backup_create"):
        result = await ctx.backups.create(
            name=payload.name, includes=payload.includes, user=principal.user, note=payload.note
        )
    return {"ok": True, **result}


@router.get("/backups/{backup_id}/verify")
async def verify_backup(
    backup_id: int, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    with respond_as(404):
        return ctx.backups.verify(backup_id)


@router.get("/backups/{backup_id}/download")
async def download_backup(
    backup_id: int,
    principal: Principal = Depends(require(BACKUPS_DOWNLOAD)),
    ctx=Depends(get_server),
):
    with respond_as(404):
        path = ctx.backups.path_for_download(backup_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/backups/{backup_id}/restore")
async def restore_backup(
    backup_id: int,
    payload: RestoreRequest,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    ctx=Depends(get_server),
):
    if not payload.confirm:
        with respond_as(404):
            target = ctx.backups.get(backup_id)
        return {
            "confirmation_required": True,
            "backup": target,
            "will_happen": [
                "The Minecraft server will be stopped if it is running",
                "The backup will be verified before anything is replaced",
                "A safety backup of the current world will be created first",
                "Current folders will be moved aside, not deleted",
                "The server will start again"
                if payload.start_after
                else "The server will stay offline",
            ],
        }
    with audit_failure(ctx, request, "backup_restore"):
        result = await ctx.backups.restore(
            backup_id,
            user=principal.user,
            start_after=payload.start_after,
            safety_backup=payload.safety_backup,
        )
    return {"ok": True, **result}


@router.delete("/backups/{backup_id}")
async def delete_backup(
    backup_id: int,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_DELETE)),
    ctx=Depends(get_server),
):
    with respond_as(404):
        result = await ctx.backups.delete(backup_id, user=principal.user)
    return {"ok": True, **result}
