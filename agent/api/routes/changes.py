"""Undo and Redo: each server's two stacks of changes (agent/changes.py)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...security.auth import Principal
from ...security.permissions import BACKUPS_RESTORE, SERVER_VIEW, require
from ...worldundo import played_seconds
from ..deps import audit, get_server
from ..errors import audit_failure
from ..responses import ChangeMoved, Changes
from .models import UndoRequest

router = APIRouter()


def _with_play(ctx, entries: list[dict], now: float) -> list[dict]:
    """What putting each one back would lose: the play since its backup."""
    return [{**e, "played_seconds": played_seconds(ctx, e["backup_at"], now)} for e in entries]


@router.get("/changes", response_model=Changes)
async def list_changes(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    now = time.time()
    return {
        "undo": _with_play(ctx, ctx.backups.changes.undo_stack(), now),
        "redo": _with_play(ctx, ctx.backups.changes.redo_stack(), now),
        "server_running": ctx.server.running,
        "blocked_by": ctx.server.held_by,
    }


@router.post("/changes/undo", response_model=ChangeMoved)
async def undo_change(
    payload: UndoRequest,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    ctx=Depends(get_server),
):
    """Reverse the newest change. Pressing it again reverses the one before."""
    with audit_failure(ctx, request, "change_undo"):
        result = await ctx.backups.changes.undo(principal.user, start_after=payload.start_after)
    audit(ctx, request, "change_undo", target=result["change"]["title"])
    return {"ok": True, **result}


@router.post("/changes/redo", response_model=ChangeMoved)
async def redo_change(
    payload: UndoRequest,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    ctx=Depends(get_server),
):
    """Put back the change undone last."""
    with audit_failure(ctx, request, "change_redo"):
        result = await ctx.backups.changes.redo(principal.user, start_after=payload.start_after)
    audit(ctx, request, "change_redo", target=result["change"]["title"])
    return {"ok": True, **result}
