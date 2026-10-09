"""What the phone app (mobile/) uses that the dashboard doesn't: the alerts
the agent sent, for the app's Notifications tab, and the phone's address on
Google's push service (FCM), for lock-screen alerts.

The alerts are the same as everywhere else (``notifications.*`` decides
which events send one and how often), kept whether or not any other channel
is turned on. A push only wakes the phone; the words come from here
(agent/notifications/fcm.py).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...notifications import fcm
from ...security.auth import Principal
from ...security.permissions import ACCOUNT, SERVER_VIEW, can_see_server, require
from ..deps import audit, get_core
from ..responses import AppAlerts, AppPhone
from .models import AppPhoneRequest

router = APIRouter()


@router.get("/alerts", response_model=AppAlerts)
async def alerts(
    after: int | None = Query(None, ge=0, description="Only alerts newer than this id"),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require(SERVER_VIEW)),
    core=Depends(get_core),
):
    """Alerts newer than ``after``, oldest first.

    A helper sees only the servers they may use; alerts about the PC itself
    (failed sign-ins, the certificate, the PC's memory) are the owner's.
    Without ``after`` nothing old is returned, only where the list is now,
    so a newly paired phone doesn't replay old alerts.
    """
    latest_row = core.db.query_one("SELECT MAX(id) AS id FROM app_alerts")
    latest = int(latest_row["id"] or 0) if latest_row else 0
    rows: list[dict] = []
    more = False
    if after is not None:
        found = core.db.query(
            "SELECT * FROM app_alerts WHERE id > ? ORDER BY id LIMIT ?",
            (after, limit),
        )
        for row in found:
            if row["server_id"] is None:
                if not principal.is_owner:
                    continue
            elif not can_see_server(principal, row["server_id"]):
                continue
            rows.append(row)
        if len(found) == limit:
            # More are waiting: the next read carries on after the last one.
            latest = found[-1]["id"]
            more = latest < int(latest_row["id"] or 0)
    return {
        "alerts": rows,
        "latest": latest,
        "more": more,
        "enabled": core.config.notifications.push_enabled,
    }


async def _phone_state(core, principal: Principal) -> dict:
    row = None
    if principal.token_hash:
        row = core.db.query_one(
            "SELECT platform, label, created_at, last_sent, last_result FROM app_phones "
            "WHERE session = ?",
            (principal.token_hash,),
        )
    return {
        "configured": await asyncio.to_thread(fcm.configured, core.config),
        "registered": row is not None,
        "phone": row,
    }


@router.get("/app/phone", response_model=AppPhone)
async def phone(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    """Whether this PC can send lock-screen alerts, and whether this phone's
    sign-in has a push address registered."""
    return await _phone_state(core, principal)


@router.put("/app/phone", response_model=AppPhone)
async def register_phone(
    payload: AppPhoneRequest,
    request: Request,
    principal: Principal = Depends(require(ACCOUNT)),
    core=Depends(get_core),
):
    """Remember this phone's push address for this sign-in. It is forgotten
    when the sign-in ends, however it ends."""
    if not principal.token_hash:
        raise HTTPException(status_code=400, detail="Sign in on the phone to get alerts there.")
    if fcm.count(core.db) >= fcm.MAX_PHONES:
        known = core.db.query_one(
            "SELECT 1 FROM app_phones WHERE session = ? OR token = ?",
            (principal.token_hash, payload.token),
        )
        if not known:
            raise HTTPException(
                status_code=409,
                detail=f"{fcm.MAX_PHONES} phones already get alerts. Sign one out first.",
            )
    fcm.register(
        core.db,
        principal.token_hash,
        principal.user,
        payload.token,
        payload.platform,
        payload.label,
    )
    audit(core, request, "app_phone_registered", detail=payload.platform)
    return await _phone_state(core, principal)


@router.delete("/app/phone", response_model=AppPhone)
async def forget_phone(
    request: Request, principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)
):
    """Stop lock-screen alerts to this phone (the app's switch turned off)."""
    if principal.token_hash and fcm.forget_session(core.db, principal.token_hash):
        audit(core, request, "app_phone_forgotten")
    return await _phone_state(core, principal)
