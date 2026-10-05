"""Permissions: what each API route and WebSocket action needs.

Every route declares the one permission it needs with ``require(...)``.
``tests/test_permissions.py`` fails if a route declares none. Today the
owner, the only account, has all of them; helper accounts (a later phase)
only add roles that hold a subset.
"""

from __future__ import annotations

from functools import cache

from fastapi import Depends, Request

from .auth import AuthError, Principal

ACCOUNT = "account.self"  # sign out, rotate or read one's own session
SERVER_VIEW = "server.view"  # status, console, players, performance, history
SERVER_CONTROL = "server.control"  # start, stop, restart, save the world
CONSOLE_SEND = "console.send"  # type commands into the Minecraft console
MODS_MANAGE = "mods.manage"  # install, remove, enable, update, roll back mods
BACKUPS_CREATE = "backups.create"
BACKUPS_DOWNLOAD = "backups.download"
BACKUPS_RESTORE = "backups.restore"  # also undoing a change, which restores
BACKUPS_DELETE = "backups.delete"
SCHEDULES_MANAGE = "schedules.manage"
SETTINGS_VIEW = "settings.view"
SETTINGS_EDIT = "settings.edit"  # includes alerts, maintenance mode, TPS command
SERVERS_MANAGE = "servers.manage"  # add or remove a server from the list
SECURITY_VIEW = "security.view"  # sessions, certificate facts, audit log
SECURITY_MANAGE = "security.manage"  # revoke every session
SYSTEM_VIEW = "system.view"  # agent-wide facts, such as the Windows startup test

ALL = frozenset(
    {
        ACCOUNT,
        SERVER_VIEW,
        SERVER_CONTROL,
        CONSOLE_SEND,
        MODS_MANAGE,
        BACKUPS_CREATE,
        BACKUPS_DOWNLOAD,
        BACKUPS_RESTORE,
        BACKUPS_DELETE,
        SCHEDULES_MANAGE,
        SETTINGS_VIEW,
        SETTINGS_EDIT,
        SERVERS_MANAGE,
        SECURITY_VIEW,
        SECURITY_MANAGE,
        SYSTEM_VIEW,
    }
)

# The permission each WebSocket message type needs. ws.py refuses any
# message type that is not listed here.
WS_ACTIONS = {
    "tail": SERVER_VIEW,
    "status": SERVER_VIEW,
}


def permissions_for(principal: Principal) -> frozenset[str]:
    """Everything, for now: there is one account and it is the owner."""
    return ALL


def check(principal: Principal, permission: str) -> None:
    if permission not in ALL:  # a typo in a route would otherwise lock everyone out
        raise ValueError(f"Unknown permission {permission!r}")
    if permission not in permissions_for(principal):
        raise AuthError("Your account is not allowed to do that", status=403)


@cache
def require(permission: str):
    """A route dependency: sign-in, then the named permission.

    The same function object is returned for the same permission, and it
    carries ``.permission`` so the test can read what each route declared.
    """
    if permission not in ALL:
        raise ValueError(f"Unknown permission {permission!r}")
    from ..api.deps import require_auth

    async def dependency(request: Request, principal: Principal = Depends(require_auth)):
        check(principal, permission)
        return principal

    dependency.permission = permission  # type: ignore[attr-defined]
    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency
