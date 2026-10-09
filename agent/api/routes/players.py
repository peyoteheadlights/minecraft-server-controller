"""Who is online and who has played, and the Players page's buttons."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...minecraft import playeractions
from ...security.auth import Principal
from ...security.permissions import PLAYERS_MANAGE, PLAYERS_OP, SERVER_VIEW, check, require
from ..deps import audit, get_server
from ..responses import Players
from .models import PlayerActionRequest

router = APIRouter()

# An operator can type any command in the game, so these need players.op,
# which only the owner has.
OPERATOR_ACTIONS = ("op", "deop")


@router.get("/players", response_model=Players)
async def players(principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)):
    return {
        "online": ctx.players.online(),
        "online_count": ctx.players.online_count(),
        "verified": ctx.players.verified,
        "source": ctx.players.verified_source,
        "known": ctx.players.all_players(),
        "max_players": ctx.config.server.max_players,
        # Who is on the whitelist, an operator or banned, from Minecraft's
        # own files. null with a reason when a file isn't there yet.
        "lists": playeractions.lists(
            ctx.config.server_dir, ctx.config.server_type.dialect, ctx.players.names_by_id()
        ),
        # Bedrock servers have no ban list; the page hides ban and unban.
        "bans": ctx.config.server_type.bans,
        "edition": ctx.config.server_type.edition,
        "running": ctx.server.running and ctx.server.state.value == "ONLINE",
        "actions": [a.to_dict() for a in ctx.player_actions.recent()[:10]],
    }


@router.get("/players/sessions")
async def player_sessions(
    username: str = "",
    limit: int = 100,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    return {"sessions": ctx.players.sessions(username or None, max(1, min(limit, 500)))}


@router.post("/players/actions")
async def player_action(
    payload: PlayerActionRequest,
    request: Request,
    principal: Principal = Depends(require(PLAYERS_MANAGE)),
    ctx=Depends(get_server),
):
    """Send whitelist, op, kick, ban or unban for one player. The answer is
    "sent"; it becomes "done" once the server's console confirms it."""
    if payload.action in OPERATOR_ACTIONS:
        check(principal, PLAYERS_OP)
    pending = await ctx.player_actions.send(
        payload.action, payload.name, payload.reason or "", confirm=payload.confirm
    )
    audit(ctx, request, f"player_{payload.action}", target=pending.name, detail=pending.command)
    return {"result": "SENT", "action": pending.to_dict()}


@router.get("/players/actions/{action_id}")
async def player_action_status(
    action_id: str,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    """Whether the server has confirmed an action yet."""
    pending = ctx.player_actions.get(action_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="That action isn't on the list any more.")
    return {"action": pending.to_dict()}
