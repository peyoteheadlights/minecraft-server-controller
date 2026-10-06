"""One server's game settings: the common server.properties values."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ... import gamesettings
from ...security.auth import Principal
from ...security.permissions import SETTINGS_EDIT, SETTINGS_VIEW, require
from ..deps import audit, get_server
from .models import GameSettingsRawRequest, GameSettingsRequest

router = APIRouter()


@router.get("/game-settings")
async def get_game_settings(
    principal: Principal = Depends(require(SETTINGS_VIEW)), ctx=Depends(get_server)
):
    """What server.properties says for each known key, and the whole file."""
    return gamesettings.view(ctx)


@router.put("/game-settings")
async def save_game_settings(
    payload: GameSettingsRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Change known keys. Every value is checked first; nothing is written
    unless all of them pass."""
    result = await gamesettings.save(ctx, updates=payload.values, user=principal.user)
    audit(ctx, request, "game_settings", detail=", ".join(result["keys"])[:300])
    return {"ok": True, **result}


@router.put("/game-settings/raw")
async def save_game_settings_raw(
    payload: GameSettingsRawRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    """Replace the whole file with text typed in Technical mode. The known
    keys in it are still checked like the form's."""
    result = await gamesettings.save(ctx, raw_text=payload.text, user=principal.user)
    audit(ctx, request, "game_settings_raw", detail=", ".join(result["keys"])[:300])
    return {"ok": True, **result}
