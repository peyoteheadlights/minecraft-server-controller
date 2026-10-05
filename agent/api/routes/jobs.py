"""Jobs: long operations (backups, restores and, later, downloads and
version changes) and their real progress. One-click undo of a safe change."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...security.auth import Principal
from ...security.permissions import BACKUPS_RESTORE, SERVER_VIEW, require
from ..deps import audit, get_core
from ..errors import audit_failure

router = APIRouter()


@router.get("/jobs")
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
    jobs = core.jobs.recent(server_id, limit=max(1, min(limit, 200)), running_only=running)
    return {"jobs": [job.to_dict() for job in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str, principal: Principal = Depends(require(SERVER_VIEW)), core=Depends(get_core)
):
    return core.jobs.get(job_id).to_dict()


@router.post("/jobs/{job_id}/undo")
async def undo_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require(BACKUPS_RESTORE)),
    core=Depends(get_core),
):
    """Undo a finished change by restoring the backup it took first. The
    undo is itself a safe change, so it can be undone too."""
    job = core.jobs.get(job_id)
    undo = (job.result or {}).get("undo")
    if job.state != "succeeded" or not undo or undo.get("kind") != "restore_backup":
        raise HTTPException(status_code=400, detail="This job has nothing to undo")
    ctx = core.get_server(job.server_id)
    with audit_failure(ctx, request, "job_undo", target=job_id):
        result = await ctx.backups.restore(int(undo["backup_id"]), user=principal.user)
    audit(ctx, request, "job_undo", target=job_id, detail=undo.get("backup"))
    return {"ok": True, **result}
