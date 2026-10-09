"""The app's own version: update checks and installs, the version numbers a
client checks, the phone pairing code, and removing the old setup.ps1 copy.

Installing an update is the owner's alone (``app.update``), always confirmed
in the dashboard first, and only ever runs the installer's own update task
(see agent/updates.py and docs/security.md).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import API_VERSION, __version__, oldcopy, pairing
from ...jobs import JobConflict
from ...security.auth import Principal
from ...security.permissions import ACCOUNT, APP_UPDATE, SETTINGS_VIEW, require
from ...updates import UpdateError
from ..deps import audit, get_core
from ..responses import (
    OldCopyRemoveResult,
    OldCopyStatus,
    PairingCode,
    UpdatePreflight,
    UpdateStarted,
    UpdateStatus,
    VersionInfo,
)

router = APIRouter()


@router.get("/version", response_model=VersionInfo)
async def version(principal: Principal = Depends(require(ACCOUNT))):
    """The app's version and the API version a client talks to. A client
    that knows an older API version still works; see CHANGELOG.md."""
    return {"version": __version__, "api_version": API_VERSION}


@router.get("/pairing", response_model=PairingCode)
async def pairing_code(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    """What the "Open on your phone" code holds: the address, port,
    certificate fingerprint and API version. No password or token."""
    return await asyncio.to_thread(pairing.pairing_code, core.config)


@router.get("/updates", response_model=UpdateStatus)
async def update_status(
    principal: Principal = Depends(require(SETTINGS_VIEW)), core=Depends(get_core)
):
    return core.updates.status()


@router.post("/updates/check", response_model=UpdateStatus)
async def check_now(principal: Principal = Depends(require(APP_UPDATE)), core=Depends(get_core)):
    """Ask GitHub for the newest release now."""
    return await core.updates.check()


@router.get("/updates/preflight", response_model=UpdatePreflight)
async def preflight(principal: Principal = Depends(require(APP_UPDATE)), core=Depends(get_core)):
    """What the confirmation needs: the version and who is playing."""
    return core.updates.preflight()


@router.post("/updates/install", response_model=UpdateStarted)
async def install(
    request: Request, principal: Principal = Depends(require(APP_UPDATE)), core=Depends(get_core)
):
    """Download the newest release's setup file, check its SHA-256, save
    the settings and database, and hand over to the installer."""
    try:
        job = core.updates.start_install(principal.user)
    except (UpdateError, JobConflict) as exc:
        audit(core, request, "app_update", result="refused", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "app_update", target=job.title)
    return {"ok": True, "job": job.to_dict()}


@router.get("/updates/old-copy", response_model=OldCopyStatus)
async def old_copy(principal: Principal = Depends(require(SETTINGS_VIEW)), core=Depends(get_core)):
    """The setup.ps1 copy the installer moved from, if it is still there."""
    return {"old_copy": await asyncio.to_thread(oldcopy.status, core.config)}


@router.post("/updates/old-copy/remove", response_model=OldCopyRemoveResult)
async def remove_old_copy(
    request: Request, principal: Principal = Depends(require(APP_UPDATE)), core=Depends(get_core)
):
    """Remove the old copy's program files. Backups, server folders and
    anything the app doesn't know are kept (agent/oldcopy.py)."""
    try:
        result = await asyncio.to_thread(oldcopy.remove, core.config)
    except oldcopy.OldCopyError as exc:
        audit(core, request, "old_copy_remove", result="refused", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(
        core,
        request,
        "old_copy_remove",
        target=result["path"],
        result="ok" if result["ok"] else "failed",
        detail="; ".join(result["failed"]) or None,
    )
    return result
