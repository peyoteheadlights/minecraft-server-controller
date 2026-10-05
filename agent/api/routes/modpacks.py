"""Importing a Modrinth modpack (.mrpack): as a new server (agent-wide) or
into an existing one (per server)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ... import modpack
from ...security.auth import Principal
from ...security.permissions import MODS_MANAGE, SERVERS_MANAGE, SETTINGS_EDIT, require
from ..deps import audit, get_core, get_server
from .models import ModpackIntoRequest, ModpackNewRequest

# Agent-wide: reading a pack, and making a new server from it.
global_router = APIRouter()
# Per server: importing into this server.
router = APIRouter()

CHUNK = 1024 * 1024


@global_router.post("/modpacks/inspect")
async def inspect_modpack(
    request: Request,
    file: UploadFile = File(...),
    server_id: str = "",
    principal: Principal = Depends(require(MODS_MANAGE)),
    core=Depends(get_core),
):
    """Upload a .mrpack and say what it holds, before anything changes.
    With ``server_id``, also what importing it into that server would do."""
    if not (file.filename or "").lower().endswith(".mrpack"):
        raise HTTPException(status_code=400, detail="Choose a Modrinth modpack file (.mrpack).")
    token, path = modpack.new_upload(core)
    size = 0
    try:
        with path.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > modpack.MAX_PACK_BYTES:
                    raise HTTPException(
                        status_code=400, detail="That pack is bigger than 1 GB, so it wasn't read."
                    )
                await asyncio.to_thread(out.write, chunk)
        pack = await asyncio.to_thread(modpack.inspect, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    result = {"token": token, "pack": pack.to_dict()}
    if server_id:
        ctx = core.get_server(server_id)
        result["into"] = modpack.plan_into(ctx, pack)
    audit(core, request, "modpack_inspect", target=pack.name)
    return result


@global_router.delete("/modpacks/{token}")
async def forget_modpack(
    token: str, principal: Principal = Depends(require(MODS_MANAGE)), core=Depends(get_core)
):
    """Throw an uploaded pack away without importing it."""
    modpack.forget(core, token)
    return {"ok": True}


@global_router.post("/modpacks/{token}/new-server")
async def modpack_new_server(
    token: str,
    payload: ModpackNewRequest,
    request: Request,
    principal: Principal = Depends(require(SERVERS_MANAGE)),
    core=Depends(get_core),
):
    """Make a new server from an uploaded pack. Minecraft is not started."""
    result = await modpack.import_new(
        core,
        token,
        name=payload.name,
        directory=payload.directory,
        memory_mb=payload.memory_mb,
        color=payload.color,
        eula_accepted=payload.eula_accepted,
        user=principal.user,
    )
    audit(core, request, "modpack_new_server", target=result["server_id"])
    return {"ok": True, **result}


@router.post("/modpack")
async def modpack_into_server(
    payload: ModpackIntoRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Import an uploaded pack into this server: stopped, backed up, its old
    add-ons moved aside, then the pack's files put in place and checked."""
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="This needs to be confirmed, because the server is stopped for it.",
        )
    result = await modpack.import_into(ctx, payload.token, user=principal.user)
    audit(ctx, request, "modpack_import", detail=result["modpack"]["name"])
    return {"ok": True, **result}
