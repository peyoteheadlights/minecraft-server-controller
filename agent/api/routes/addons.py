"""Bedrock add-ons: the packs on a Bedrock server, uploading new ones, and
turning them on and off in its world (agent/addons.py)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Request, UploadFile

from ... import addons
from ...security.auth import Principal
from ...security.permissions import MODS_MANAGE, SERVER_VIEW, require
from ..deps import audit, get_server
from ..errors import audit_failure
from ..responses import AddonList, AddonResult
from .models import AddonToggleRequest

router = APIRouter()


def _bedrock_only(ctx) -> None:
    if not ctx.config.server_type.addons:
        raise addons.AddonError(
            f"{ctx.config.server_type.name} servers don't use Bedrock add-ons. Their add-ons "
            "are on the Mods page."
        )


@router.get("/addons", response_model=AddonList)
async def list_addons(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """The packs someone added to this Bedrock server, and which are on."""
    _bedrock_only(ctx)
    return await asyncio.to_thread(addons.view, ctx)


@router.post("/addons/upload", response_model=AddonResult)
async def upload_addon(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    """Install a .mcpack, .mcaddon or .mctemplate's packs and turn them on
    in this server's world (when it has one yet)."""
    _bedrock_only(ctx)
    data = await file.read(addons.MAX_UPLOAD_BYTES + 1)
    name = file.filename or ""
    with audit_failure(ctx, request, "addon_upload", target=name):

        async def change():
            world_made = await asyncio.to_thread(lambda: addons.world_path(ctx).is_dir())
            return await asyncio.to_thread(addons.install, ctx, name, data, world_made)

        result = await ctx.mod_change(f"Adding {name[:60]}", change, principal.user)
    audit(ctx, request, "addon_upload", target=name)
    return {"ok": True, **result}


@router.put("/addons/{pack_uuid}", response_model=AddonResult)
async def toggle_addon(
    pack_uuid: str,
    payload: AddonToggleRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    """Turn a pack on or off in this server's world."""
    _bedrock_only(ctx)
    with audit_failure(ctx, request, "addon_toggle", target=pack_uuid):

        async def change():
            return await asyncio.to_thread(addons.set_enabled, ctx, pack_uuid, payload.enabled)

        result = await ctx.mod_change("Changing an add-on", change, principal.user)
    audit(ctx, request, "addon_toggle", target=pack_uuid, detail="on" if payload.enabled else "off")
    return {"ok": True, **result}


@router.delete("/addons/{pack_uuid}", response_model=AddonResult)
async def remove_addon(
    pack_uuid: str,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    """Turn a pack off and move it out of the server folder."""
    _bedrock_only(ctx)
    with audit_failure(ctx, request, "addon_remove", target=pack_uuid):

        async def change():
            return await asyncio.to_thread(addons.remove, ctx, pack_uuid)

        result = await ctx.mod_change("Removing an add-on", change, principal.user)
    audit(ctx, request, "addon_remove", target=pack_uuid)
    return {"ok": True, **result}
