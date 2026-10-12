"""Jobs: long operations (backups, restores, downloads, version changes) and
their real progress."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...security.auth import Principal
from ...security.permissions import (
    BACKUPS_RESTORE,
    SERVER_VIEW,
    can_see_server,
    check,
    check_server,
    require,
)
from ..deps import audit, get_core
from ..errors import audit_failure
from ..responses import Job, JobList, JobUndone

router = APIRouter()


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    server_id: str | None = None,
    running: bool = False,
    limit: int = 50,
    principal: Principal = Depends(require(SERVER_VIEW)),
    core=Depends(get_core),
):
    """Recent jobs, newest first; every server's unless one is named."""
    if server_id is not None and server_id not in core.servers:
        raise HTTPException(status_code=404, detail=f"There is no server with the id '{server_id}'")
    check_server(principal, server_id)
    jobs = core.jobs.recent(server_id, limit=max(1, min(limit, 200)), running_only=running)
    # A helper limited to some servers sees only their jobs.
    return {"jobs": [job.to_dict() for job in jobs if can_see_server(principal, job.server_id)]}


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(
    job_id: str, principal: Principal = Depends(require(SERVER_VIEW)), core=Depends(get_core)
):
    job = core.jobs.get(job_id)
    check_server(principal, job.server_id)
    return job.to_dict()


@router.post("/jobs/{job_id}/undo", response_model=JobUndone, deprecated=True)
async def undo_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    core=Depends(get_core),
):
    """Undo a finished change while it is still the server's newest one.
    Replaced by ``POST /api/servers/{id}/changes/undo``, which goes on back
    one change at a time."""
    job = core.jobs.get(job_id)
    check_server(principal, job.server_id)
    check(principal, BACKUPS_RESTORE, job.server_id)
    if job.state != "succeeded" or not (job.result or {}).get("undo"):
        raise HTTPException(status_code=400, detail="This job has nothing to undo")
    ctx = core.get_server(job.server_id)
    stack = ctx.backups.changes.undo_stack()
    if not stack or stack[0]["job_id"] != job_id:
        raise HTTPException(
            status_code=409,
            detail="Only the newest change can be undone. Use Undo on the Backups page "
            "to go back one change at a time.",
        )
    with audit_failure(ctx, request, "job_undo", target=job_id):
        result = await ctx.backups.changes.undo(principal.user)
    audit(ctx, request, "job_undo", target=job_id, detail=result["change"]["backup"])
    return {"ok": True, **result}
