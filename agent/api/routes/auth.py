"""Liveness probe and sign-in. The only routes that need no token are
/api/health and /api/auth/login."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ...security.auth import AccountError, Principal
from ...security.permissions import ACCOUNT, permissions_for, require
from ..deps import audit, client_ip, get_core
from .models import LoginRequest, PasswordChangeRequest, PreferencesRequest

router = APIRouter()


@router.get("/health")
async def health(core=Depends(get_core)):
    """Unauthenticated liveness probe. Deliberately reveals nothing."""
    return {
        "ok": True,
        "agent_uptime": time.time() - core.started_at,
        "auth_configured": core.auth.configured,
    }


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, core=Depends(get_core)):
    return core.auth.login(
        payload.username, payload.password, source_ip=client_ip(request), label=payload.label
    )


@router.post("/auth/logout")
async def logout(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    core.auth.logout(principal)
    return {"ok": True}


@router.post("/auth/rotate")
async def rotate(
    request: Request, principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)
):
    return core.auth.rotate(principal, source_ip=client_ip(request))


@router.get("/auth/me")
async def me(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    return {
        **principal.to_dict(),
        "permissions": sorted(permissions_for(principal)),
        "preferences": core.auth.preferences(principal.user),
    }


@router.post("/account/password")
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    principal: Principal = Depends(require(ACCOUNT)),
    core=Depends(get_core),
):
    """A helper changes their own password. The owner's is reset on the PC."""
    try:
        core.auth.change_own_password(principal, payload.current, payload.new)
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "password_change")
    return {"ok": True}


@router.get("/account/preferences")
async def get_preferences(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    return core.auth.preferences(principal.user)


@router.put("/account/preferences")
async def set_preferences(
    payload: PreferencesRequest,
    principal: Principal = Depends(require(ACCOUNT)),
    core=Depends(get_core),
):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    return core.auth.set_preferences(principal.user, updates)
