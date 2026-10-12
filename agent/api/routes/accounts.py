"""Moderator accounts ("helpers" in code until Phase 12): friends' own
logins, with the permissions the owner ticked on each server.

Only the owner manages them (users.manage). A helper changes their own
password through /account/password in auth.py. The owner's own password is
not managed here at all: it is reset on the PC (installer/reset_password.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...events import Event
from ...security.auth import AccountError, Principal
from ...security.permissions import (
    HELPER,
    USERS_MANAGE,
    catalogue,
    grant,
    level_of,
    require,
)
from ..deps import audit, get_core
from .models import AccountCreateRequest, AccountUpdateRequest

router = APIRouter()


def _servers(core, ids: list[str] | None) -> list[str] | None:
    if ids is None:
        return None
    unknown = [i for i in ids if i not in core.servers]
    if unknown:
        raise HTTPException(status_code=400, detail=f"There is no server '{unknown[0]}'.")
    if not ids:
        raise HTTPException(status_code=400, detail="Pick at least one server, or every server.")
    return sorted(set(ids))


def _grant(permissions: list[str]) -> frozenset[str]:
    try:
        return grant(permissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _described(permissions: frozenset[str]) -> dict:
    return {"permissions": sorted(permissions), "level": level_of(permissions)}


def _moderator(core, account: dict) -> dict:
    """One moderator as the owner's screens show them: what they may do on
    each server, and what new servers give them."""
    access = account.pop("access")
    return {
        **account,
        "all_servers": access.all_servers,
        "new_server": _described(access.new_server),
        "access": [
            {"id": ctx.server_id, "name": ctx.name, **_described(access.on(ctx.server_id))}
            for ctx in core.servers.values()
        ],
    }


@router.get("/accounts")
async def list_accounts(
    principal: Principal = Depends(require(USERS_MANAGE)), core=Depends(get_core)
):
    return {
        "owner": core.auth.owner_username,
        "helpers": [_moderator(core, account) for account in core.auth.accounts()],
        "permissions": catalogue(),
        "servers": [{"id": ctx.server_id, "name": ctx.name} for ctx in core.servers.values()],
    }


@router.post("/accounts")
async def add_account(
    payload: AccountCreateRequest,
    request: Request,
    principal: Principal = Depends(require(USERS_MANAGE)),
    core=Depends(get_core),
):
    servers = _servers(core, payload.servers)
    given = _grant(payload.permissions) if payload.permissions is not None else None
    if given is not None and not given:
        raise HTTPException(status_code=400, detail="Tick at least one thing they may do.")
    try:
        account = core.auth.create_account(
            payload.username, payload.password, servers, by=principal.user, permissions=given
        )
    except AccountError as exc:
        audit(
            core, request, "helper_add", target=payload.username, result="refused", detail=str(exc)
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "helper_add", target=account["username"])
    await core.bus.publish(
        Event(
            type="helper_added",
            level="info",
            message=f"{principal.user} added the moderator {account['username']}",
            data={"username": account["username"], "role": HELPER},
        )
    )
    return {"ok": True, "username": account["username"]}


@router.put("/accounts/{username}")
async def change_account(
    username: str,
    payload: AccountUpdateRequest,
    request: Request,
    principal: Principal = Depends(require(USERS_MANAGE)),
    core=Depends(get_core),
):
    """Change a moderator. Their next request already follows the change:
    nobody is signed out, except by a new password."""
    servers: list[str] | None | bool = False
    if payload.servers is not None:
        servers = _servers(core, payload.servers)
    elif payload.all_servers is True and payload.grants is None and payload.new_server is None:
        servers = None  # the older form: every server
    grants = None
    if payload.grants is not None:
        if payload.grants:
            _servers(core, list(payload.grants))
        grants = {sid: _grant(perms) for sid, perms in payload.grants.items()}
    new_server = _grant(payload.new_server) if payload.new_server is not None else None
    try:
        account = core.auth.update_account(
            username,
            by=principal.user,
            servers=servers,
            password=payload.password,
            grants=grants,
            all_servers=payload.all_servers if servers is False else None,
            new_server=new_server,
        )
    except AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "helper_change", target=account["username"])
    return {"ok": True, "username": account["username"]}


@router.delete("/accounts/{username}")
async def remove_account(
    username: str,
    request: Request,
    principal: Principal = Depends(require(USERS_MANAGE)),
    core=Depends(get_core),
):
    try:
        name = core.auth.delete_account(username, by=principal.user)
    except AccountError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(core, request, "helper_remove", target=name)
    await core.bus.publish(
        Event(
            type="helper_removed",
            level="warn",
            message=f"{principal.user} removed the moderator {name}",
            data={"username": name},
        )
    )
    return {"ok": True, "removed": name}
