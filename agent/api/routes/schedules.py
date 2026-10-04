"""Scheduled tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...security.auth import Principal
from ..deps import audit, get_core, require_auth
from ..errors import respond_as
from .models import ScheduleRequest

router = APIRouter()


@router.get("/schedules")
async def list_schedules(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"schedules": core.scheduler.list_schedules(), "tasks": list(core.scheduler.handlers)}


@router.post("/schedules")
async def create_schedule(payload: ScheduleRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    row = core.scheduler.add(payload.name, payload.task, payload.kind, payload.expr,
                             payload.payload, payload.enabled)
    audit(core, request, "schedule_create", target=payload.name)
    return {"ok": True, "schedule": row}


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, payload: ScheduleRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    row = core.scheduler.update(schedule_id, name=payload.name, task=payload.task,
                                kind=payload.kind, expr=payload.expr,
                                payload=payload.payload, enabled=payload.enabled)
    audit(core, request, "schedule_update", target=str(schedule_id))
    return {"ok": True, "schedule": row}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(404):
        core.scheduler.delete(schedule_id)
    audit(core, request, "schedule_delete", target=str(schedule_id))
    return {"ok": True}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule(schedule_id: int, request: Request,
                       principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(404):
        row = core.scheduler.get(schedule_id)
        result = await core.scheduler.run_task(row)
    audit(core, request, "schedule_run_now", target=row["name"])
    return {"ok": True, "result": result}

