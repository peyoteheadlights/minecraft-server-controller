"""World undo: the timeline of points this server's world can go back to."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import checklist, worldundo
from ...security.auth import Principal
from ...security.permissions import BACKUPS_RESTORE, SERVER_VIEW, SETTINGS_EDIT, require
from ..deps import audit, get_server
from ..errors import audit_failure
from .models import WorldUndoRequest

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
