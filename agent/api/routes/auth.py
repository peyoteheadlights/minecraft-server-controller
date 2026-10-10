"""Liveness probe and sign-in. The only routes that need no token are
/api/health and /api/auth/login."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import API_VERSION
from ...security.auth import AccountError, Principal
from ...security.permissions import ACCOUNT, permissions_for, require
from ..deps import audit, client_ip, get_core
from ..responses import DeviceList, Health, LoginResult, Me, Ok
from .models import LoginRequest, PasswordChangeRequest, PreferencesRequest

router = APIRouter()


@router.get("/health", response_model=Health)
async def health(core=Depends(get_core)):
    """Unauthenticated liveness probe. Deliberately reveals nothing."""
    return {
        "ok": True,
        "agent_uptime": time.time() - core.started_at,
        "auth_configured": core.auth.configured,
        # Lets a phone app say "update the app" before anyone signs in.
        "api_version": API_VERSION,
    }


@router.post("/auth/login", response_model=LoginResult)
async def login(payload: LoginRequest, request: Request, core=Depends(get_core)):
    return core.auth.login(
        payload.username,
        payload.password,
        source_ip=client_ip(request),
        label=payload.device or payload.label,
        remember=payload.remember,
    )


@router.post("/auth/logout", response_model=Ok)
async def logout(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    core.auth.logout(principal)
    return {"ok": True}


@router.post("/auth/rotate")
async def rotate(
    request: Request, principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)
):
    return core.auth.rotate(principal, source_ip=client_ip(request))


@router.get("/sessions", response_model=DeviceList)
async def devices(principal: Principal = Depends(require(ACCOUNT)), core=Depends(get_core)):
    """Signed-in devices: the owner sees every account's, a helper their own."""
    return {
        "sessions": core.auth.devices(principal),
        "remember_days": core.config.security.remember_days,
    }


@router.delete("/sessions/{session_id}", response_model=Ok)
async def sign_out_device(
    session_id: str,
    request: Request,
    principal: Principal = Depends(require(ACCOUNT)),
    core=Depends(get_core),
):
    """Sign one device out. Its next request is refused."""
    result = core.auth.sign_out_device(principal, session_id)
    audit(core, request, "device_signed_out", target=result["user"], detail=result["label"])
    return {"ok": True}


@router.get("/auth/me", response_model=Me)
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
