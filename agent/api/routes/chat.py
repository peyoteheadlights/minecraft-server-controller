"""In-game chat: what the console printed, and messages sent as "Server"."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...minecraft.chat import say
from ...security.auth import Principal
from ...security.permissions import CHAT_SEND, SERVER_VIEW, require
from ..deps import audit, get_server
from ..responses import ChatLog, ChatSent
from .models import ChatRequest

router = APIRouter()


@router.get("/chat", response_model=ChatLog)
async def chat_log(
    lines: int = 100, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """The recent chat this server's console printed. Live messages arrive
    on the websocket as "chat" events."""
    return {
        "messages": [m.to_dict() for m in ctx.chat.tail(max(1, min(lines, 400)))],
        "running": ctx.server.running and ctx.server.state.value == "ONLINE",
        "kept": len(ctx.chat),
    }


@router.post("/chat", response_model=ChatSent)
async def send_chat(
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(require(CHAT_SEND)),
    ctx=Depends(get_server),
):
    """Say something to everyone in the game, as "Server"."""
    message = await say(ctx.server, payload.message)
    audit(ctx, request, "chat_send", detail=message[:200])
    return {
        "result": "SENT",
        "detail": "The message went to the server console. It appears in the chat once "
        "the server prints it.",
        "message": message,
    }
