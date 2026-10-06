"""Get help: the zip of logs and the system check to send to someone
helping. Its file list is shown first (GET), then it is made (POST) and
downloaded by token. Owner only (help.bundle)."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ... import helpbundle
from ...security.auth import Principal
from ...security.permissions import HELP_BUNDLE, require
from ..deps import audit, get_core
from .models import HelpBundleRequest

router = APIRouter()


@router.get("/help-bundle")
async def help_bundle_contents(
    principal: Principal = Depends(require(HELP_BUNDLE)), core=Depends(get_core)
):
    items = await asyncio.to_thread(helpbundle.plan, core.config)
    return {"files": [item.to_dict() for item in items]}


@router.post("/help-bundle")
async def make_help_bundle(
    payload: HelpBundleRequest,
    request: Request,
    principal: Principal = Depends(require(HELP_BUNDLE)),
    core=Depends(get_core),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Look over the file list, then confirm.")
    token, target = helpbundle.new_target(core.config)
    try:
        files = await asyncio.to_thread(helpbundle.build, core.config, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    audit(core, request, "help_bundle")
    filename = f"minecraft-server-control-help-{time.strftime('%Y%m%d-%H%M')}.zip"
    return {"ok": True, "token": token, "filename": filename, "files": files}


@router.get("/help-bundle/{token}")
async def download_help_bundle(
    token: str,
    filename: str = "help.zip",
    principal: Principal = Depends(require(HELP_BUNDLE)),
    core=Depends(get_core),
):
    path = helpbundle.path_for(core.config, token)
    if path is None:
        raise HTTPException(
            status_code=404, detail="That file isn't there any more. Make it again."
        )
    safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "help.zip"
    if not safe.endswith(".zip"):
        safe += ".zip"
    return FileResponse(path, media_type="application/zip", filename=safe)
