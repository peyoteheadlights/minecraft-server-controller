"""Helper accounts: friends' own logins with limited access.

Only the owner manages them (users.manage). A helper changes their own
password through /account/password in auth.py. The owner's own password is
not managed here at all: it is reset on the PC (installer/reset_password.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...events import Event
from ...security.auth import AccountError, Principal
from ...security.permissions import HELPER, HELPER_PERMISSIONS, USERS_MANAGE, require
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


@router.get("/accounts")
async def list_accounts(
    principal: Principal = Depends(require(USERS_MANAGE)), core=Depends(get_core)
):
    return {
        "owner": core.auth.owner_username,
        "helpers": core.auth.accounts(),
        "helper_can": sorted(HELPER_PERMISSIONS),
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
    try:
        account = core.auth.create_account(
            payload.username, payload.password, servers, by=principal.user
        )
    except AccountError as exc:
        audit(core, request, "helper_add", target=payload.username, result="refused", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "helper_add", target=account["username"])
    await core.bus.publish(
        Event(
            type="helper_added",
            level="info",
            message=f"{principal.user} added the helper {account['username']}",
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
    servers: list[str] | None | bool = False
    if payload.all_servers is True:
        servers = None
    elif payload.servers is not None:
        servers = _servers(core, payload.servers)
    try:
        account = core.auth.update_account(
            username, by=principal.user, servers=servers, password=payload.password
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
            message=f"{principal.user} removed the helper {name}",
            data={"username": name},
        )
    )
    return {"ok": True, "removed": name}
