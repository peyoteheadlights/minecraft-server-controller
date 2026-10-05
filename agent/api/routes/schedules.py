"""Scheduled tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...security.auth import Principal
from ...security.permissions import SCHEDULES_MANAGE, SERVER_VIEW, require
from ..deps import audit, get_server
from ..errors import respond_as
from .models import ScheduleRequest

router = APIRouter()


@router.get("/schedules")
async def list_schedules(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return {"schedules": ctx.scheduler.list_schedules(), "tasks": list(ctx.scheduler.handlers)}


@router.post("/schedules")
async def create_schedule(
    payload: ScheduleRequest,
    request: Request,
    principal: Principal = Depends(require(SCHEDULES_MANAGE)),
    ctx=Depends(get_server),
):
    row = ctx.scheduler.add(
        payload.name, payload.task, payload.kind, payload.expr, payload.payload, payload.enabled
    )
    audit(ctx, request, "schedule_create", target=payload.name)
    return {"ok": True, "schedule": row}


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int,
    payload: ScheduleRequest,
    request: Request,
    principal: Principal = Depends(require(SCHEDULES_MANAGE)),
    ctx=Depends(get_server),
):
    row = ctx.scheduler.update(
        schedule_id,
        name=payload.name,
        task=payload.task,
        kind=payload.kind,
        expr=payload.expr,
        payload=payload.payload,
        enabled=payload.enabled,
    )
    audit(ctx, request, "schedule_update", target=str(schedule_id))
    return {"ok": True, "schedule": row}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    request: Request,
    principal: Principal = Depends(require(SCHEDULES_MANAGE)),
    ctx=Depends(get_server),
):
    with respond_as(404):
        ctx.scheduler.delete(schedule_id)
    audit(ctx, request, "schedule_delete", target=str(schedule_id))
    return {"ok": True}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule(
    schedule_id: int,
    request: Request,
    principal: Principal = Depends(require(SCHEDULES_MANAGE)),
    ctx=Depends(get_server),
):
    with respond_as(404):
        row = ctx.scheduler.get(schedule_id)
        result = await ctx.scheduler.run_task(row)
    audit(ctx, request, "schedule_run_now", target=row["name"])
    return {"ok": True, "result": result}
