"""Who is online and who has played."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...security.auth import Principal
from ...security.permissions import SERVER_VIEW, require
from ..deps import get_server

router = APIRouter()


@router.get("/players")
async def players(principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)):
    return {
        "online": ctx.players.online(),
        "online_count": ctx.players.online_count(),
        "verified": ctx.players.verified,
        "source": ctx.players.verified_source,
        "known": ctx.players.all_players(),
        "max_players": ctx.config.server.max_players,
    }


@router.get("/players/sessions")
async def player_sessions(
    username: str = "",
    limit: int = 100,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    return {"sessions": ctx.players.sessions(username or None, max(1, min(limit, 500)))}
