"""Duplicating a server."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ... import duplicate as duplicate_module
from ...security.auth import Principal
from ...security.permissions import SERVERS_MANAGE, require
from ..deps import audit, get_server
from .models import DuplicateRequest

router = APIRouter()


@router.get("/duplicate")
async def duplicate_options(
    principal: Principal = Depends(require(SERVERS_MANAGE)), ctx=Depends(get_server)
):
    """A suggested name and folder for a copy of this server."""
    return duplicate_module.suggestion(ctx.core, ctx)


@router.post("/duplicate")
async def duplicate_server(
    payload: DuplicateRequest,
    request: Request,
    principal: Principal = Depends(require(SERVERS_MANAGE)),
    ctx=Depends(get_server),
):
    """Start copying this server into a new one. Runs as a job; the new
    server appears on the list when the copy has been checked."""
    job = await duplicate_module.start_duplicate(
        ctx.core,
        ctx,
        name=payload.name,
        directory=payload.directory,
        world=payload.world,
        user=principal.user,
    )
    audit(ctx, request, "server_duplicate", target=payload.name, detail=payload.world)
    return {"ok": True, "job": job.to_dict()}
