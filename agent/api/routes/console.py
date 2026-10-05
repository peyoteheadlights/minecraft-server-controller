"""The console buffer, the event history and crash records."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ...security.auth import Principal
from ...security.permissions import CONSOLE_SEND, SERVER_VIEW, require
from ..deps import audit, get_server

router = APIRouter()


@router.get("/logs")
async def logs(
    lines: int = 100,
    since: int = 0,
    search: str = "",
    level: str = "",
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    lines = max(1, min(int(lines), 500))
    if search:
        found = ctx.server.console.search(search, limit=lines, level=level or None)
    elif since:
        found = ctx.server.console.since(since, limit=lines)
    elif level:
        found = ctx.server.console.by_level(level, limit=lines)
    else:
        found = ctx.server.console.tail(lines)
    return {
        "lines": [line.to_dict() for line in found],
        "buffered": len(ctx.server.console),
        "buffer_limit": ctx.server.console.maxlen,
    }


@router.get("/logs/download", response_class=PlainTextResponse)
async def download_logs(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    body = "\n".join(ctx.server.console.all_raw())
    filename = f"console-{time.strftime('%Y%m%d-%H%M%S')}.log"
    return PlainTextResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/logs/clear")
async def clear_console(
    request: Request, principal: Principal = Depends(require(CONSOLE_SEND)), ctx=Depends(get_server)
):
    """Clears the agent's in-memory view only. Minecraft's own log files are untouched."""
    ctx.server.console.clear()
    audit(ctx, request, "console_clear")
    return {"ok": True}


@router.get("/events")
async def events(
    limit: int = 100, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    limit = max(1, min(int(limit), 500))
    await ctx.core.events.flush()
    return {"events": ctx.db.recent_events(ctx.server.server_id, limit)}


@router.get("/crashes")
async def crashes(
    limit: int = 50, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return {"crashes": ctx.crashes.list_crashes(max(1, min(limit, 200)))}


@router.get("/crashes/{crash_id}")
async def crash_detail(
    crash_id: int, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    row = ctx.crashes.get_crash(crash_id)
    if not row:
        raise HTTPException(status_code=404, detail="That crash record does not exist")
    return row
