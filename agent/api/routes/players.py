"""Who is online and who has played."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...security.auth import Principal
from ..deps import get_core, require_auth

router = APIRouter()


@router.get("/players")
async def players(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {
        "online": core.players.online(),
        "online_count": core.players.online_count(),
        "verified": core.players.verified,
        "source": core.players.verified_source,
        "known": core.players.all_players(),
        "max_players": core.config.server.max_players,
    }


@router.get("/players/sessions")
async def player_sessions(username: str = "", limit: int = 100,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"sessions": core.players.sessions(username or None, max(1, min(limit, 500)))}

