"""Liveness probe and sign-in. The only routes that need no token are
/api/health, /api/auth/login and the two invite routes (an invite is what
lets a new moderator in)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import API_VERSION
from ...events import Event
from ...security.auth import AccountError, InviteError, Principal
from ...security.permissions import (
    ACCOUNT,
    SERVER_PERMISSIONS,
    can_see_server,
    held_anywhere,
    legacy_names,
    on_server,
    require,
)
from ..deps import audit, client_ip, get_core
from ..responses import DeviceList, Health, InviteCheck, LoginResult, Me, Ok
from .models import (
    InviteAcceptRequest,
    InviteCheckRequest,
    LoginRequest,
    PasswordChangeRequest,
    PreferencesRequest,
)

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
        # The phone app keeps its sign-in until signed out, so a phone signs
        # in once after scanning the code.
        until_signed_out=payload.remember and payload.phone,
    )


@router.post("/invite/check", response_model=InviteCheck)
async def check_invite(payload: InviteCheckRequest, request: Request, core=Depends(get_core)):
    """Who an invite is for, before they choose a password. No sign-in: the
    invite is what lets them in. A wrong one counts as a failed sign-in."""
    try:
        return core.auth.check_invite(payload.token, source_ip=client_ip(request))
    except InviteError as exc:
        raise _invite_problem(exc) from exc


@router.post("/invite/accept", response_model=LoginResult)
async def accept_invite(payload: InviteAcceptRequest, request: Request, core=Depends(get_core)):
    """Choose the password an invite is for, and sign this phone in."""
    ip = client_ip(request)
    try:
        result = core.auth.accept_invite(
            payload.token, payload.password, source_ip=ip, label=payload.device
        )
    except InviteError as exc:
        raise _invite_problem(exc) from exc
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    where = f" on {payload.device}" if payload.device else ""
    await core.bus.publish(
        Event(
            type="helper_invite_used",
            level="info",
            message=f"{result['user']} set up their account{where}",
            data={"username": result["user"], "device": payload.device},
        )
    )
    return result


def _invite_problem(exc: InviteError) -> HTTPException:
    # 410 Gone for an invite that was real once; 404 for one that never was.
    status = 404 if exc.reason == "unknown" else 410
    return HTTPException(status_code=status, detail=exc.message)


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
    held = held_anywhere(principal)
    return {
        **principal.to_dict(),
        "permissions": legacy_names(held),
        "account_permissions": sorted(held - SERVER_PERMISSIONS),
        "server_permissions": {
            sid: sorted(on_server(principal, sid) & SERVER_PERMISSIONS)
            for sid in core.servers
            if can_see_server(principal, sid)
        },
        "preferences": core.auth.preferences(principal.user),
    }


@router.post("/account/password", response_model=Ok)
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
