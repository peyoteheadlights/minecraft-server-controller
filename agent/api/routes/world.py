"""This server's world: the undo timeline, bringing a world in (a zip or a
folder on the PC), and taking it out as a zip for single-player."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ... import checklist, worldimport, worldundo
from ...security.auth import Principal
from ...security.permissions import (
    BACKUPS_DOWNLOAD,
    BACKUPS_RESTORE,
    SERVER_VIEW,
    SETTINGS_EDIT,
    WORLD_REPLACE,
    require,
)
from ..deps import audit, get_server
from ..errors import audit_failure
from .models import WorldFolderRequest, WorldImportRequest, WorldUndoRequest

CHUNK = 1024 * 1024

router = APIRouter()


@router.get("/world/timeline")
async def world_timeline(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return worldundo.timeline(ctx)


@router.post("/world/undo")
async def world_undo(
    payload: WorldUndoRequest,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    ctx=Depends(get_server),
):
    """Put the world back to one point on the timeline. A fresh backup of
    the world as it is now is always taken first, so this can be undone."""
    if not payload.confirm:
        raise HTTPException(
            status_code=400, detail="Confirm this first: it replaces the world as it is now."
        )
    with audit_failure(ctx, request, "world_undo", target=str(payload.backup_id)):
        result = await worldundo.restore(ctx, payload.backup_id, user=principal.user)
    audit(ctx, request, "world_undo", target=result["point"]["name"])
    return {"ok": True, **result}


@router.get("/getting-started")
async def getting_started(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """The first-visit checklist, each item ticked from measured state."""
    return checklist.status(ctx)


@router.post("/getting-started/dismiss")
async def dismiss_getting_started(
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    audit(ctx, request, "getting_started_dismiss")
    return checklist.dismiss(ctx)


@router.post("/world/import/upload")
async def upload_world(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require(WORLD_REPLACE)),
    ctx=Depends(get_server),
):
    """Upload a world zip and say what it is. Nothing changes until the
    import is confirmed."""
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Choose a world saved as a .zip file.")
    token, path = worldimport.new_upload(ctx.core)
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > worldimport.MAX_ZIP_BYTES:
                    raise HTTPException(
                        status_code=400, detail="That zip is bigger than 20 GB, so it wasn't read."
                    )
                await asyncio.to_thread(out.write, chunk)
        info, _ = await asyncio.to_thread(worldimport.inspect_zip, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    audit(ctx, request, "world_upload", target=info.name or info.folder_name)
    return {"token": token, "world": info.to_dict()}


@router.post("/world/import/folder")
async def pick_world_folder(
    payload: WorldFolderRequest,
    principal: Principal = Depends(require(WORLD_REPLACE)),
    ctx=Depends(get_server),
):
    """Read a world folder on the PC and say what it is."""
    info, path = await asyncio.to_thread(worldimport.inspect_folder, payload.path)
    token = worldimport.remember_folder(ctx.core, path)
    return {"token": token, "world": info.to_dict()}


@router.get("/world/saves")
async def single_player_worlds(
    principal: Principal = Depends(require(WORLD_REPLACE)), ctx=Depends(get_server)
):
    """The worlds in single-player Minecraft's saves folder on this PC."""
    folder = await asyncio.to_thread(worldimport.saves_folder)
    worlds = await asyncio.to_thread(worldimport.saved_worlds)
    return {"folder": str(folder) if folder else None, "worlds": worlds}


@router.post("/world/import")
async def import_world(
    payload: WorldImportRequest,
    request: Request,
    principal: Principal = Depends(require(WORLD_REPLACE)),
    ctx=Depends(get_server),
):
    """Replace this server's world with the uploaded or picked one."""
    if not payload.confirm:
        raise HTTPException(
            status_code=400, detail="Confirm this first: it replaces this server's world."
        )
    with audit_failure(ctx, request, "world_import"):
        result = await worldimport.import_world(ctx, payload.token, user=principal.user)
    request.state.audited = True  # import_world writes its own audit row
    return {"ok": True, **result}


@router.delete("/world/import/{token}")
async def forget_world(
    token: str, principal: Principal = Depends(require(WORLD_REPLACE)), ctx=Depends(get_server)
):
    """Throw an uploaded world away without importing it."""
    worldimport.forget(ctx.core, token)
    return {"ok": True}


@router.post("/world/download")
async def pack_world(
    request: Request,
    principal: Principal = Depends(require(BACKUPS_DOWNLOAD)),
    ctx=Depends(get_server),
):
    """Pack the world as a zip for single-player. Download it with the token."""
    result = await worldimport.prepare_download(ctx, user=principal.user)
    audit(ctx, request, "world_download")
    return {"ok": True, **result}


@router.get("/world/download/{token}")
async def download_world(
    token: str,
    filename: str = "world.zip",
    principal: Principal = Depends(require(BACKUPS_DOWNLOAD)),
    ctx=Depends(get_server),
):
    path = worldimport.download_path(ctx.core, token)
    safe = "".join(c for c in filename if c.isalnum() or c in " ._-").strip() or "world.zip"
    if not safe.lower().endswith(".zip"):
        safe += ".zip"
    return FileResponse(path, media_type="application/zip", filename=safe)
