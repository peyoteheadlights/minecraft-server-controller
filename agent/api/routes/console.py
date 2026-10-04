"""The console buffer, the event history and crash records."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ...security.auth import Principal
from ..deps import audit, get_core, require_auth

router = APIRouter()


@router.get("/logs")
async def logs(
    lines: int = 100,
    since: int = 0,
    search: str = "",
    level: str = "",
    principal: Principal = Depends(require_auth),
    core=Depends(get_core),
):
    lines = max(1, min(int(lines), 500))
    if search:
        found = core.server.console.search(search, limit=lines, level=level or None)
    elif since:
        found = core.server.console.since(since, limit=lines)
    elif level:
        found = core.server.console.by_level(level, limit=lines)
    else:
        found = core.server.console.tail(lines)
    return {
        "lines": [line.to_dict() for line in found],
        "buffered": len(core.server.console),
        "buffer_limit": core.server.console.maxlen,
    }


@router.get("/logs/download", response_class=PlainTextResponse)
async def download_logs(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    body = "\n".join(core.server.console.all_raw())
    filename = f"console-{time.strftime('%Y%m%d-%H%M%S')}.log"
    return PlainTextResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/logs/clear")
async def clear_console(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    """Clears the agent's in-memory view only. Minecraft's own log files are untouched."""
    core.server.console.clear()
    audit(core, request, "console_clear")
    return {"ok": True}


@router.get("/events")
async def events(
    limit: int = 100, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    limit = max(1, min(int(limit), 500))
    await core.events.flush()
    return {"events": core.db.recent_events(core.server.server_id, limit)}


@router.get("/crashes")
async def crashes(
    limit: int = 50, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    return {"crashes": core.crashes.list_crashes(max(1, min(limit, 200)))}


@router.get("/crashes/{crash_id}")
async def crash_detail(
    crash_id: int, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    row = core.crashes.get_crash(crash_id)
    if not row:
        raise HTTPException(status_code=404, detail="That crash record does not exist")
    return row
