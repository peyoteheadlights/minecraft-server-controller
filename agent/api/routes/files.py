"""The folder picker. Lists folder names only; owner only (files.browse)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ... import filebrowse
from ...security.auth import Principal
from ...security.permissions import FILES_BROWSE, require

router = APIRouter()


@router.get("/folders")
async def browse_folders(path: str = "", principal: Principal = Depends(require(FILES_BROWSE))):
    try:
        return await asyncio.to_thread(filebrowse.listing, path or None)
    except filebrowse.BrowseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
