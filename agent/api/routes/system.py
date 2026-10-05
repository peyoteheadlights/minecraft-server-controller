"""Agent-wide routes: the server list (adding and removing servers), the
port suggestion, and the Windows startup test."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import colors
from ...config import PROJECT_ROOT, ConfigError
from ...ports import read_properties_port
from ...security.auth import Principal
from ...security.paths import PathSafetyError, check_server_folder
from ...security.permissions import SERVER_VIEW, SERVERS_MANAGE, SYSTEM_VIEW, require
from ..deps import audit, get_core
from .models import ServerAddRequest

router = APIRouter()

# Tried in this order when the add-server form leaves the jar empty.
DEFAULT_JARS = ("fabric-server-launch.jar", "server.jar")


@router.get("/servers")
async def servers(principal: Principal = Depends(require(SERVER_VIEW)), core=Depends(get_core)):
    """Every registered server with its measured state, players and uptime."""
    rows = []
    for ctx in core.servers.values():
        row = ctx.summary()
        row["current"] = row["default"]
        rows.append(row)
    return {
        "servers": rows,
        "default": core.config.default_server_id,
        "palette": colors.palette(),
        "next_color": colors.next_unused(ctx.color for ctx in core.servers.values()),
    }


def _new_id(name: str, taken: list[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "server"
    if not base[0].isalnum():
        base = f"server-{base}"
    candidate, number = base, 2
    lowered = {t.lower() for t in taken}
    while candidate in lowered or candidate in ("con", "prn", "aux", "nul"):
        candidate = f"{base}-{number}"
        number += 1
    return candidate


@router.post("/servers")
async def add_server(
    payload: ServerAddRequest,
    request: Request,
    principal: Principal = Depends(require(SERVERS_MANAGE)),
    core=Depends(get_core),
):
    """Register an existing Minecraft server folder. Nothing in the folder is
    changed and Minecraft is not started."""
    color = None
    if payload.color:
        try:
            color = colors.normalise(payload.color)
        except colors.ColorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    jar = payload.jar.strip()
    if not jar:
        from pathlib import Path

        folder = Path(payload.directory.strip()).expanduser()
        jar = next((j for j in DEFAULT_JARS if (folder / j).is_file()), DEFAULT_JARS[0])
    registered = [(ctx.name, ctx.config.server_dir) for ctx in core.servers.values()]
    try:
        directory = check_server_folder(
            payload.directory,
            jar,
            protected=[PROJECT_ROOT, core.config.data_dir],
            registered=registered,
        )
    except PathSafetyError as exc:
        audit(core, request, "server_add", target=payload.name, result="refused", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    server_id = payload.id.strip() if payload.id else _new_id(payload.name, core.config.server_ids)
    warnings = []
    port = read_properties_port(directory)
    if port is None:
        port = core.ports.suggest() or 25565
        warnings.append(
            "server.properties does not set a port yet, so Minecraft will use 25565 when it "
            f"first starts. Port {port} is free if you want to set server-port to it."
        )
    else:
        owner = core.ports.used().get(("tcp", port))
        if owner:
            warnings.append(
                f"server.properties uses port {port}, which the server "
                f"'{core.servers[owner].name}' also uses. Only one of them can run at a time "
                "until you change server-port in one of them."
            )
    entry = {
        "id": server_id,
        "name": payload.name.strip(),
        "directory": str(directory),
        "jar": jar,
        # The Java program is the agent's own setting, never the dashboard's.
        "java": core.config.server.java,
        "port": port,
    }
    try:
        ctx = await core.add_server(entry, user=principal.user)
    except ConfigError as exc:
        audit(core, request, "server_add", target=payload.name, result="failed", detail=str(exc))
        raise
    if color:
        core.db.set_server_color(ctx.server_id, color)
    return {"ok": True, "server": ctx.summary(), "warnings": warnings}


@router.delete("/servers/{server_id}")
async def remove_server(
    server_id: str,
    request: Request,
    principal: Principal = Depends(require(SERVERS_MANAGE)),
    core=Depends(get_core),
):
    """Take a server off the list. Its folder, world and backups stay."""
    result = await core.remove_server(server_id, user=principal.user)
    return {"ok": True, **result}


@router.get("/ports/suggest")
async def suggest_port(
    protocol: str = "tcp",
    principal: Principal = Depends(require(SERVER_VIEW)),
    core=Depends(get_core),
):
    if protocol not in ("tcp", "udp"):
        raise HTTPException(status_code=400, detail="protocol must be tcp or udp")
    port = core.ports.suggest(protocol)
    used = [
        {"protocol": proto, "port": number, "server_id": owner}
        for (proto, number), owner in sorted(core.ports.used().items())
    ]
    return {"port": port, "protocol": protocol, "used": used}


@router.get("/system/startup")
async def windows_startup_test(principal: Principal = Depends(require(SYSTEM_VIEW))):
    """Test Windows Startup.

    Reads the registered scheduled task back from Windows, compares it with
    this installation, checks for the old service and duplicate entries, and
    includes the agent's own record of its last startup. Read-only.
    """
    import asyncio

    try:
        from installer.autostart import report
    except ImportError as exc:
        raise HTTPException(
            status_code=500, detail=f"The startup inspector could not be loaded: {exc}"
        ) from exc
    return await asyncio.to_thread(report)
