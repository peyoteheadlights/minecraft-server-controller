"""The "How friends join" card's addresses."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from ... import joininfo
from ...security.auth import Principal
from ...security.permissions import SERVER_VIEW, require
from ..deps import get_server

router = APIRouter()


@router.get("/join")
async def how_to_join(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """The addresses and port friends type into Minecraft, read from this
    PC. Asking Tailscale runs its command, so not on the event loop."""
    return await asyncio.to_thread(joininfo.join_info, ctx)
