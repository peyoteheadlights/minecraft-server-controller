"""Move to a new PC: "Export everything" to one file. Owner only
(data.export). The other side is the installer's "Import from another PC"
(installer/import_from_pc.py), which runs on the new PC, not over the
network."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ... import transfer
from ...security.auth import Principal
from ...security.permissions import DATA_EXPORT, require
from ..deps import audit, get_core
from .models import ExportRequest

router = APIRouter()
TOKEN_RE = re.compile(transfer.TOKEN_RE_TEXT)


@router.get("/export")
async def export_sizes(
    principal: Principal = Depends(require(DATA_EXPORT)), core=Depends(get_core)
):
    """How big each part would be, measured from disk, before choosing."""
    return await asyncio.to_thread(transfer.estimate, core)


@router.post("/export")
async def start_export(
    payload: ExportRequest,
    request: Request,
    principal: Principal = Depends(require(DATA_EXPORT)),
    core=Depends(get_core),
):
    """Start writing the export file as a job. Its result has the token to
    download it with."""
    options = transfer.Options(
        worlds=payload.worlds,
        backups=payload.backups,
        secrets=payload.secrets,
        passphrase=payload.passphrase or "",
    )
    if options.secrets and len(options.passphrase) < transfer.MIN_PASSPHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"Choose a passphrase of at least {transfer.MIN_PASSPHRASE} characters to "
            "lock the passwords and keys with.",
        )
    folder = transfer.folder(core.config)
    token = secrets.token_hex(16)
    target = folder / f"{token}.zip"

    async def run(job) -> dict[str, Any]:
        total = await asyncio.to_thread(transfer.count_items, core, options)
        job.step("Writing the export file", total=total, unit="files")
        try:
            manifest = await asyncio.to_thread(transfer.export, core, target, options, job.advance)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return {
            "token": token,
            "size_bytes": target.stat().st_size,
            "servers": len(manifest["servers"]),
            "filename": f"minecraft-server-control-export-{time.strftime('%Y%m%d')}.zip",
        }

    job = core.jobs.start("export", "Exporting everything", run, user=principal.user)
    audit(
        core,
        request,
        "export",
        detail=f"worlds={options.worlds} backups={options.backups} secrets={options.secrets}",
    )
    return {"ok": True, "job_id": job.id}


@router.get("/export/{token}")
async def download_export(
    token: str,
    filename: str = "export.zip",
    principal: Principal = Depends(require(DATA_EXPORT)),
    core=Depends(get_core),
):
    path = transfer.folder(core.config) / f"{token}.zip"
    if not TOKEN_RE.match(token) or not path.is_file():
        raise HTTPException(status_code=404, detail="That file isn't there any more. Export again.")
    safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "export.zip"
    if not safe.endswith(".zip"):
        safe += ".zip"
    return FileResponse(path, media_type="application/zip", filename=safe)
