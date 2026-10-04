"""Agent-wide information that is not about one Minecraft server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...security.auth import Principal
from ..deps import get_core, require_auth

router = APIRouter()


@router.get("/servers")
async def servers(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """One entry today. The data model already keys everything by server_id,
    so a second agent can be added without a schema change."""
    rows = core.db.list_servers()
    for row in rows:
        row["current"] = row["id"] == core.server.server_id
        row["state"] = core.server.state.value if row["current"] else "UNKNOWN"
    return {"servers": rows}


@router.get("/system/startup")
async def windows_startup_test(principal: Principal = Depends(require_auth)):
    """Test Windows Startup.

    Reads the registered scheduled task back from Windows, compares it with
    this installation, checks for the old service and duplicate entries, and
    includes the agent's own record of its last startup. Read-only.
    """
    import asyncio
    try:
        from installer.autostart import report
    except ImportError as exc:
        raise HTTPException(status_code=500,
                            detail=f"The startup inspector could not be loaded: {exc}") from exc
    return await asyncio.to_thread(report)

