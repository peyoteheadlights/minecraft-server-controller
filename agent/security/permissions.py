"""Permissions: what each API route and WebSocket action needs, and which
role holds which.

Every route declares the one permission it needs with ``require(...)``, and
``tests/test_building_blocks.py`` fails if a route declares none. There are
two roles:

  * **Owner**: the account in .env (and the API token). Holds everything.
  * **Helper**: a friend's own login, made by the owner on the Helpers page.
    Can start, stop and restart, manage players, chat, back up and view
    everything, and nothing else: no settings, no deleting or restoring
    backups, no mods, no version changes, no console commands, no user
    management. A helper can also be limited to some servers.

A permission that is not in HELPER is the owner's alone. New permissions
are therefore Owner-only until someone adds them to HELPER on purpose.
Every check runs on the agent, for every API route and WebSocket action;
the dashboard hiding a button is only a convenience.
"""

from __future__ import annotations

from functools import cache

from fastapi import Depends, Request

from .auth import AuthError, Principal

ACCOUNT = "account.self"  # sign out, rotate or read one's own session
SERVER_VIEW = "server.view"  # status, console, players, performance, history
SERVER_CONTROL = "server.control"  # start, stop, restart, save the world
CONSOLE_SEND = "console.send"  # type commands into the Minecraft console
PLAYERS_MANAGE = "players.manage"  # whitelist, operator, kick, ban and unban
CHAT_SEND = "chat.send"  # say something to everyone in the game
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
USERS_MANAGE = "users.manage"  # add, change and remove helper accounts
FILES_BROWSE = "files.browse"  # list folders on the PC, for the folder picker
WORLD_REPLACE = "world.replace"  # import a world over a server's own
DATA_EXPORT = "data.export"  # "Export everything" for moving to a new PC
HELP_BUNDLE = "help.bundle"  # the "Get help" file of logs and checks

ALL = frozenset(
    {
        ACCOUNT,
        SERVER_VIEW,
        SERVER_CONTROL,
        CONSOLE_SEND,
        PLAYERS_MANAGE,
        CHAT_SEND,
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
        USERS_MANAGE,
        FILES_BROWSE,
        WORLD_REPLACE,
        DATA_EXPORT,
        HELP_BUNDLE,
    }
)

OWNER = "owner"
HELPER = "helper"

# What a helper may do. Everything else is the owner's alone.
HELPER_PERMISSIONS = frozenset(
    {
        ACCOUNT,
        SERVER_VIEW,
        SERVER_CONTROL,
        PLAYERS_MANAGE,
        CHAT_SEND,
        BACKUPS_CREATE,
        SETTINGS_VIEW,
        SYSTEM_VIEW,
    }
)

ROLES: dict[str, frozenset[str]] = {OWNER: ALL, HELPER: HELPER_PERMISSIONS}

# The permission each WebSocket message type needs. ws.py refuses any
# message type that is not listed here.
WS_ACTIONS = {
    "tail": SERVER_VIEW,
    "status": SERVER_VIEW,
}


def permissions_for(principal: Principal) -> frozenset[str]:
    """The permissions of the principal's role. An unknown role has none."""
    return ROLES.get(principal.role, frozenset())


def can_see_server(principal: Principal, server_id: str | None) -> bool:
    """Whether this account may see (and act on) that server at all. A
    helper limited to some servers sees only those."""
    if principal.servers is None or server_id is None:
        return True
    return server_id in principal.servers


def check_server(principal: Principal, server_id: str | None) -> None:
    if not can_see_server(principal, server_id):
        raise AuthError("Your account can't use this server.", status=403)


def check(principal: Principal, permission: str) -> None:
    if permission not in ALL:  # a typo in a route would otherwise lock everyone out
        raise ValueError(f"{permission!r} isn't a permission this app has.")
    if permission not in permissions_for(principal):
        raise AuthError("Your account isn't allowed to do that.", status=403)


@cache
def require(permission: str):
    """A route dependency: sign-in, then the named permission.

    The same function object is returned for the same permission, and it
    carries ``.permission`` so the test can read what each route declared.
    """
    if permission not in ALL:
        raise ValueError(f"{permission!r} isn't a permission this app has.")
    from ..api.deps import require_auth

    async def dependency(request: Request, principal: Principal = Depends(require_auth)):
        check(principal, permission)
        return principal

    dependency.permission = permission  # type: ignore[attr-defined]
    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency
