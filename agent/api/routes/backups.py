"""Creating, verifying, downloading, restoring and deleting backups."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ...security.auth import Principal
from ...security.permissions import (
    BACKUPS_CREATE,
    BACKUPS_DELETE,
    BACKUPS_DOWNLOAD,
    BACKUPS_RESTORE,
    SERVER_VIEW,
    SETTINGS_EDIT,
    require,
)
from ...backups import offsite
from ...config import PROJECT_ROOT
from ...security.paths import PathSafetyError
from ..deps import audit, get_server
from ..errors import audit_failure, respond_as
from .models import BackupRequest, OffsiteRequest, RestoreRequest

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


@router.get("/backups/offsite")
async def offsite_status(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """Where second copies go, and whether that folder can be reached now."""
    root = ctx.backups.offsite_root
    return {
        "directory": str(root) if root else "",
        "unavailable": offsite.unavailable_reason(root) if root else None,
        "subfolder": str(offsite.target_folder(root, ctx.server_id)) if root else None,
    }


@router.put("/backups/offsite")
async def set_offsite(
    payload: OffsiteRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Choose (or clear) the folder for second copies. Existing backups are
    not copied by this; new ones are, and any one can be copied from the list."""
    value = ""
    if payload.directory.strip():
        protected = [PROJECT_ROOT, ctx.core.config.data_dir, ctx.config.backup_dir]
        protected += [other.config.server_dir for other in ctx.core.servers.values()]
        try:
            value = str(offsite.check_folder(payload.directory, protected))
        except PathSafetyError as exc:
            audit(ctx, request, "offsite_folder", result="refused", detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    previous = ctx.config.backups.offsite_directory
    ctx.config.set("backups.offsite_directory", value)
    try:
        ctx.config.save()
    except OSError as exc:
        ctx.config.set("backups.offsite_directory", previous)
        raise HTTPException(status_code=500, detail=f"The setting couldn't be saved: {exc}") from exc
    audit(ctx, request, "offsite_folder", detail=value or "off")
    return {"ok": True, "directory": value}


@router.post("/backups/{backup_id}/copy")
async def copy_backup(
    backup_id: int,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_CREATE)),
    ctx=Depends(get_server),
):
    """Copy one backup off the PC now (again, if the last try failed)."""
    with audit_failure(ctx, request, "backup_copy", target=str(backup_id)):
        result = await ctx.backups.copy_again(backup_id, user=principal.user)
    return {"ok": result.get("state") == "ok", "copy": result}
