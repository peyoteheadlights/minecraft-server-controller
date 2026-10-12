"""Permissions: what each API route and WebSocket action needs, and who
holds which.

Every route declares the one permission it needs with ``require(...)``, and
``tests/test_building_blocks.py`` fails if a route declares none. There are
two kinds of account:

  * **Owner**: the account in .env (and the API token). Holds everything.
  * **Moderator** (still "helper" in code, the database and the API until
    the Phase 12 rename): a friend's own login, made by the owner. The owner
    ticks what they may do on each server (SERVER_PERMISSIONS), usually by
    picking a level (LEVELS). A server with nothing ticked is hidden from
    them. On top of that every moderator holds MODERATOR_ACCOUNT: their own
    account and reading the agent's non-secret facts.

A permission in neither set is the owner's alone, so a new permission is
owner-only until someone adds it to SERVER_PERMISSIONS on purpose. Every
check runs on the agent, for every API route and WebSocket action; the apps
hiding a button is only a convenience.
"""

from __future__ import annotations

from functools import cache

from fastapi import Depends, Request

from .auth import AuthError, Principal

ACCOUNT = "account.self"  # sign out, rotate or read one's own session
SERVER_VIEW = "server.view"  # state, players online, performance, backups list
CONSOLE_READ = "console.read"  # the console, chat log, Activity and crashes
SERVER_CONTROL = "server.control"  # start, stop, restart, save the world
CONSOLE_SEND = "console.send"  # type commands into the Minecraft console
PLAYERS_MANAGE = "players.manage"  # whitelist, kick, ban and unban
# Making someone an op (or taking it away) is its own permission: an op can
# type any command in the game, so it is console access by another door.
PLAYERS_OP = "players.op"
CHAT_SEND = "chat.send"  # say something to everyone in the game
MODS_MANAGE = "mods.manage"  # install, remove, enable, update, roll back mods
BACKUPS_CREATE = "backups.create"
BACKUPS_DOWNLOAD = "backups.download"
BACKUPS_RESTORE = "backups.restore"  # also Undo and Redo, which restore
BACKUPS_DELETE = "backups.delete"
SCHEDULES_MANAGE = "schedules.manage"
SETTINGS_VIEW = "settings.view"
SETTINGS_GAME = "settings.game"  # Game settings: server.properties
# Server settings: how Command Block runs one server, including its version,
# server type, memory and crossplay.
SETTINGS_SERVER = "settings.server"
# PC settings: alerts, maintenance, keeping the PC awake, browser alerts and
# a server's off-PC backup folder (a folder on the PC). Owner only.
PC_SETTINGS = "pc.settings"
SERVERS_MANAGE = "servers.manage"  # add, duplicate or remove a server
SECURITY_VIEW = "security.view"  # sessions, certificate facts, audit log
SECURITY_MANAGE = "security.manage"  # revoke every session
SYSTEM_VIEW = "system.view"  # agent-wide facts, such as the Windows startup test
USERS_MANAGE = "users.manage"  # add, change and remove moderators
FILES_BROWSE = "files.browse"  # list folders on the PC, for the folder picker
WORLD_REPLACE = "world.replace"  # import a world over a server's own
DATA_EXPORT = "data.export"  # "Export everything" for moving to a new PC
HELP_BUNDLE = "help.bundle"  # the "Get help" file of logs and checks
APP_UPDATE = "app.update"  # check for, and install, a new version; remove the old copy

# The permission the apps released before part 6 look for. It is never
# checked; the sign-in answer lists it for anyone holding one of its parts.
LEGACY_SETTINGS_EDIT = "settings.edit"

ALL = frozenset(
    {
        ACCOUNT,
        SERVER_VIEW,
        CONSOLE_READ,
        SERVER_CONTROL,
        CONSOLE_SEND,
        PLAYERS_MANAGE,
        PLAYERS_OP,
        CHAT_SEND,
        MODS_MANAGE,
        BACKUPS_CREATE,
        BACKUPS_DOWNLOAD,
        BACKUPS_RESTORE,
        BACKUPS_DELETE,
        SCHEDULES_MANAGE,
        SETTINGS_VIEW,
        SETTINGS_GAME,
        SETTINGS_SERVER,
        PC_SETTINGS,
        SERVERS_MANAGE,
        SECURITY_VIEW,
        SECURITY_MANAGE,
        SYSTEM_VIEW,
        USERS_MANAGE,
        FILES_BROWSE,
        WORLD_REPLACE,
        DATA_EXPORT,
        HELP_BUNDLE,
        APP_UPDATE,
    }
)

OWNER = "owner"
HELPER = "helper"

# What the owner can tick for a moderator on one server.
SERVER_PERMISSIONS = frozenset(
    {
        SERVER_VIEW,
        CONSOLE_READ,
        SERVER_CONTROL,
        CONSOLE_SEND,
        PLAYERS_MANAGE,
        PLAYERS_OP,
        CHAT_SEND,
        MODS_MANAGE,
        BACKUPS_CREATE,
        BACKUPS_DOWNLOAD,
        BACKUPS_RESTORE,
        BACKUPS_DELETE,
        SCHEDULES_MANAGE,
        SETTINGS_GAME,
        SETTINGS_SERVER,
        WORLD_REPLACE,
    }
)

# What every moderator holds whatever their servers: their own account, and
# reading settings and the PC's facts (secrets are never in either).
MODERATOR_ACCOUNT = frozenset({ACCOUNT, SETTINGS_VIEW, SYSTEM_VIEW})

# The switches, grouped as the apps show them. Seeing the server is not a
# switch: it comes with anything ticked.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("server", (SERVER_CONTROL, CONSOLE_READ, CONSOLE_SEND)),
    ("players", (PLAYERS_MANAGE, CHAT_SEND, PLAYERS_OP)),
    ("addons", (MODS_MANAGE,)),
    ("backups", (BACKUPS_CREATE, BACKUPS_RESTORE, BACKUPS_DOWNLOAD, BACKUPS_DELETE, WORLD_REPLACE)),
    ("settings", (SETTINGS_GAME, SETTINGS_SERVER, SCHEDULES_MANAGE)),
)

# Shown only in Technical mode: rarer, and riskier.
TECHNICAL = frozenset({CONSOLE_SEND, PLAYERS_OP, BACKUPS_DOWNLOAD, BACKUPS_DELETE, WORLD_REPLACE})
# These let someone do anything in the game: the apps warn when they're ticked.
WARN = frozenset({CONSOLE_SEND, PLAYERS_OP})
# A switch that can't work without another one brings it along.
NEEDS: dict[str, frozenset[str]] = {
    PLAYERS_OP: frozenset({PLAYERS_MANAGE}),
    CONSOLE_SEND: frozenset({CONSOLE_READ}),
}

START_AND_STOP = frozenset({SERVER_VIEW, SERVER_CONTROL})
LOOK_AFTER_IT = START_AND_STOP | {CONSOLE_READ, PLAYERS_MANAGE, CHAT_SEND, BACKUPS_CREATE}
RUN_IT = LOOK_AFTER_IT | {
    MODS_MANAGE,
    SETTINGS_GAME,
    SETTINGS_SERVER,
    BACKUPS_RESTORE,
    SCHEDULES_MANAGE,
}
# The levels, smallest first. A set that is none of them is "custom".
LEVELS: dict[str, frozenset[str]] = {
    "start_and_stop": START_AND_STOP,
    "look_after_it": LOOK_AFTER_IT,
    "run_it": RUN_IT,
}
DEFAULT_LEVEL = "look_after_it"

# The permission each WebSocket message type needs. ws.py refuses any
# message type that is not listed here.
WS_ACTIONS = {
    "tail": CONSOLE_READ,
    "status": SERVER_VIEW,
}


def grant(permissions) -> frozenset[str]:
    """A set the owner ticked for one server, made whole: anything ticked
    brings seeing the server and whatever it needs; nothing ticked stays
    nothing. Refuses a permission that isn't a per-server one."""
    wanted = frozenset(permissions or ())
    unknown = wanted - SERVER_PERMISSIONS
    if unknown:
        raise ValueError(f"{sorted(unknown)[0]!r} can't be given on a server.")
    if not wanted:
        return frozenset()
    out = set(wanted) | {SERVER_VIEW}
    for permission in wanted:
        out |= NEEDS.get(permission, frozenset())
    return frozenset(out)


def level_of(permissions) -> str:
    """The level a set matches, "custom" if none, "none" when empty."""
    held = frozenset(permissions or ())
    if not held:
        return "none"
    for name, level in LEVELS.items():
        if held == level:
            return name
    return "custom"


def catalogue() -> dict:
    """The levels and switches, for the apps to show (they keep no copy)."""
    return {
        "levels": [{"id": name, "permissions": sorted(level)} for name, level in LEVELS.items()],
        "default_level": DEFAULT_LEVEL,
        "groups": [{"id": name, "permissions": list(group)} for name, group in GROUPS],
        "technical": sorted(TECHNICAL),
        "warn": sorted(WARN),
        "needs": {name: sorted(needed) for name, needed in NEEDS.items()},
    }


def on_server(principal: Principal, server_id: str | None) -> frozenset[str]:
    """What this account may do on that server. The owner: everything."""
    if principal.access is None:
        return ALL
    if server_id is None:
        return frozenset()
    return principal.access.on(server_id)


def held_anywhere(principal: Principal) -> frozenset[str]:
    """Every permission this account holds on at least one server, plus its
    account-wide ones: the flat list the sign-in answer has always given."""
    if principal.access is None:
        return ALL
    return principal.access.anywhere() | MODERATOR_ACCOUNT


def legacy_names(held: frozenset[str]) -> list[str]:
    """``held`` for apps released before part 6, which still look for the
    old single settings permission."""
    names = set(held)
    if held & {SETTINGS_GAME, SETTINGS_SERVER, PC_SETTINGS}:
        names.add(LEGACY_SETTINGS_EDIT)
    return sorted(names)


def can_see_server(principal: Principal, server_id: str | None) -> bool:
    """Whether this account may see (and act on) that server at all: a
    moderator sees the servers where the owner ticked something."""
    if principal.access is None or server_id is None:
        return True
    return bool(principal.access.on(server_id))


def check_server(principal: Principal, server_id: str | None) -> None:
    if not can_see_server(principal, server_id):
        raise AuthError("Your account can't use this server.", status=403)


def check(principal: Principal, permission: str, server_id: str | None = None) -> None:
    """Refuse unless the account holds ``permission``: on ``server_id`` when
    one is named, else on at least one server (the agent-wide lists, which
    then show only that account's servers)."""
    if permission not in ALL:  # a typo in a route would otherwise lock everyone out
        raise ValueError(f"{permission!r} isn't a permission this app has.")
    if principal.access is None or permission in MODERATOR_ACCOUNT:
        return
    if permission in SERVER_PERMISSIONS:
        held = principal.access.on(server_id) if server_id else principal.access.anywhere()
        if permission in held:
            return
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
        # A per-server route's server, set by deps.server_access, which runs
        # first: the permission is checked on that server.
        check(principal, permission, getattr(request.state, "server_id", None))
        return principal

    dependency.permission = permission  # type: ignore[attr-defined]
    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency
