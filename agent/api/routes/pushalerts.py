"""Phone alerts: which phones are signed up, and signing one up."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...events import Event
from ...notifications import push
from ...notifications.dispatcher import PUSH_TEST_TITLE
from ...security.auth import Principal
from ...security.permissions import SETTINGS_EDIT, SETTINGS_VIEW, require
from ..deps import audit, get_core
from .models import PushSubscribeRequest, PushUnsubscribeRequest

router = APIRouter()


@router.get("/push")
async def push_status(
    principal: Principal = Depends(require(SETTINGS_VIEW)), core=Depends(get_core)
):
    """What a phone needs to sign up, and which phones already have.

    The public key is meant to be handed to the browser; the private half
    never leaves the agent.
    """
    return {
        "configured": bool(core.config.vapid_public_key and core.config.vapid_private_key),
        "public_key": core.config.vapid_public_key,
        "enabled": core.config.notifications.push_enabled,
        "phones": push.listed(core.db),
        "setup_command": "python -m installer.make_push_keys",
    }


@router.post("/push/subscribe")
async def subscribe(
    payload: PushSubscribeRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    """Remember a browser's push subscription, so alerts can reach it."""
    if not core.config.vapid_private_key:
        raise HTTPException(
            status_code=409,
            detail="Phone alerts aren't set up yet. Run: python -m installer.make_push_keys",
        )
    subscription = push.Subscription.from_browser(payload.subscription, label=payload.label)
    stored = push.store(core.db, subscription, user=principal.user)
    audit(core, request, "push_subscribe", target=stored["label"] or "phone")
    return {"ok": True, "phone": stored, "phones": push.listed(core.db)}


@router.post("/push/unsubscribe")
async def unsubscribe(
    payload: PushUnsubscribeRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    removed = push.forget(core.db, payload.endpoint)
    audit(core, request, "push_unsubscribe", result="ok" if removed else "not_found")
    return {"ok": True, "removed": removed, "phones": push.listed(core.db)}


@router.post("/push/test")
async def test_push(
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    core=Depends(get_core),
):
    """Send one test alert to every phone signed up."""
    event = Event(
        type="server_started",
        level="success",
        message="Test alert from Minecraft Server Control",
        data={"startup_seconds": 0.0},
    )
    sent = await core.notifier.send_push(event, title=PUSH_TEST_TITLE)
    audit(core, request, "push_test", detail=str(sent))
    return {"channel": "push", "sent": sent, "phones": push.listed(core.db)}
