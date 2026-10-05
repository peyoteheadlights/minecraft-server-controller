"""Server types, versions, version and type changes, and crossplay.

Agent-wide: the type comparison table and each type's version list, and
creating a new server. Per server: the preflight before a change, the
change itself, rolling it back, and the Bedrock crossplay switch.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import crossplay as crossplay_module
from ... import servertypes
from ...security.auth import Principal
from ...security.permissions import (
    SERVER_VIEW,
    SERVERS_MANAGE,
    SETTINGS_EDIT,
    require,
)
from ...servertypes import create as create_module
from ...servertypes import install as install_module
from ...servertypes import versions as versions_module
from ..deps import audit, get_core, get_server
from .models import (
    CreateServerRequest,
    CrossplayRequest,
    VersionChangeRequest,
)

# Agent-wide routes (the types, their versions, creating a server).
global_router = APIRouter()
# Per-server routes, served under /api/servers/{server_id}/.
router = APIRouter()


# ---------------------------------------------------------------- the types
@global_router.get("/server-types")
async def list_types(principal: Principal = Depends(require(SERVER_VIEW))):
    """Every server type with its capabilities. The dashboard's comparison
    table is generated from this, so it cannot drift from what the app does."""
    return {
        "types": servertypes.catalog(),
        "recommended": servertypes.RECOMMENDED,
        "default": servertypes.DEFAULT_TYPE,
    }


@global_router.get("/server-types/{type_id}/versions")
async def type_versions(type_id: str, principal: Principal = Depends(require(SERVER_VIEW))):
    """The Minecraft versions this type offers, from its official source."""
    server_type = servertypes.get(type_id)
    found = await versions_module.list_versions(server_type.id)
    return versions_module.versions_payload(server_type.id, found)


@global_router.get("/new-server/options")
async def new_server_options(
    principal: Principal = Depends(require(SERVERS_MANAGE)), core=Depends(get_core)
):
    """What the New server panel needs before anything is chosen."""
    return await create_module.options(core)


@global_router.post("/new-server")
async def create_server(
    payload: CreateServerRequest,
    request: Request,
    principal: Principal = Depends(require(SERVERS_MANAGE)),
    core=Depends(get_core),
):
    """Create a brand-new server: folder, settings, download and set-up.
    Minecraft is not started; the person presses Start themselves."""
    return await create_module.create_server(
        core,
        name=payload.name,
        directory=payload.directory,
        type_id=payload.type,
        minecraft=payload.minecraft_version,
        loader=payload.loader_version,
        memory_mb=payload.memory_mb,
        color=payload.color,
        eula_accepted=payload.eula_accepted,
        user=principal.user,
    )


# ---------------------------------------------------- one server's version
@router.get("/version")
async def current_version(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """This server's type and version, as observed, plus what a change kept."""
    status = ctx.server.status()
    server_type = ctx.config.server_type
    record = ctx.db.get_setting("version_change") or {}
    return {
        "type": server_type.id,
        "capabilities": server_type.to_dict(),
        # Only what the console reported. null means Unknown.
        "minecraft_version": status["minecraft_version"],
        "minecraft_version_source": status["minecraft_version_source"],
        "loader_version": status["loader_version"],
        "loader_name": status["loader_name"],
        "detected_type": status["server_type_detected"],
        "pending_version": status["pending_version"],
        "eula_required": status["eula_required"],
        "last_change": {
            "at": record.get("at"),
            "type": record.get("type"),
            "previous_type": record.get("previous_type"),
            "minecraft_version": record.get("minecraft_version"),
            "can_roll_back": bool(record.get("previous")),
            "install_log": record.get("install_log"),
            "moved_aside": (record.get("content_moved_aside") or {}).get("moved", []),
        }
        if record
        else None,
    }


@router.post("/version/preflight")
async def version_preflight(
    payload: VersionChangeRequest,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    """What a change would do, in plain words, before anything happens."""
    return await install_module.preflight(
        ctx,
        payload.type or ctx.config.server.type,
        payload.minecraft_version,
        payload.loader_version,
    )


@router.post("/version")
async def change_version(
    payload: VersionChangeRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Change this server's version, or its type. Stops the server, takes a
    verified backup, installs, checks, and keeps the old files to go back to."""
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="This change needs to be confirmed, because the server is stopped for it.",
        )
    result = await install_module.change_version(
        ctx,
        payload.type or ctx.config.server.type,
        payload.minecraft_version,
        payload.loader_version,
        user=principal.user,
        start_after=payload.start_after,
    )
    audit(ctx, request, "version_change", detail=payload.minecraft_version)
    return {"ok": True, **result}


@router.post("/version/roll-back")
async def roll_back_version(
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Put the version that was there before the last change back."""
    result = await install_module.roll_back(ctx, user=principal.user)
    audit(ctx, request, "version_rollback")
    return {"ok": True, **result}


@router.post("/eula")
async def accept_eula(
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Record that the person accepted Minecraft's rules for this server.
    Only ever called from their own tick: nothing accepts them for them."""
    if not ctx.config.server_dir_configured:
        raise HTTPException(status_code=400, detail="This server's folder isn't set.")
    path = create_module.write_eula(ctx.config.server_dir, True)
    ctx.server.eula_required = False
    audit(ctx, request, "eula_accepted")
    return {"ok": True, "file": str(path), "url": create_module.EULA_URL}


# ---------------------------------------------------------------- crossplay
@router.get("/crossplay")
async def crossplay_status(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """Whether Bedrock players can join, the port they use, and what differs."""
    status = crossplay_module.status(ctx)
    port = ctx.core.ports.bedrock_port_of(ctx)
    return {
        **status,
        "address_port": port.port if port else None,
        "suggested_port": None if status["enabled"] else ctx.core.ports.suggest_bedrock(),
        # The address Bedrock players type. Only from a measured Tailscale
        # address: null with a reason when this PC's address isn't known.
        # Asking Tailscale runs its command, so not on the event loop.
        **(await asyncio.to_thread(crossplay_module.address, status)),
    }


@router.put("/crossplay")
async def set_crossplay(
    payload: CrossplayRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Turn "Let Bedrock players join" on or off."""
    if payload.enabled:
        result = await crossplay_module.enable(ctx, payload.port, user=principal.user)
    else:
        result = await crossplay_module.disable(ctx, user=principal.user)
    audit(ctx, request, "crossplay", detail="on" if payload.enabled else "off")
    return {"ok": True, **result}
