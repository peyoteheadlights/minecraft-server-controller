"""Liveness probe and sign-in. The only routes that need no token are
/api/health and /api/auth/login."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...security.auth import Principal
from ..deps import client_ip, get_core, require_auth
from .models import LoginRequest

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
async def logout(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    core.auth.logout(principal)
    return {"ok": True}


@router.post("/auth/rotate")
async def rotate(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    return core.auth.rotate(principal, source_ip=client_ip(request))


@router.get("/auth/me")
async def me(principal: Principal = Depends(require_auth)):
    return principal.to_dict()
