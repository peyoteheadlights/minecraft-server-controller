"""REST API, one router per area.

Every route except /api/health and /api/auth/login requires a bearer token,
and every route declares the permission it needs (see
agent/security/permissions.py). No route accepts a shell string or a command
line: the only free text that reaches the operating system is a Minecraft
console command, validated by agent.minecraft.commands first. The one route
that takes a folder path, adding a server, checks it with
agent.security.paths.check_server_folder.

PER_SERVER routers act on one Minecraft server and live under
/api/servers/{server_id}/. The ones that existed before there were several
servers (LEGACY_PER_SERVER) are also served unprefixed, acting on the first
server, for one release. GLOBAL routers are about the agent itself.
"""

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from ..deps import mark_alias, server_access
from . import (
    accounts,
    auth,
    backups,
    chat,
    console,
    duplicate,
    files,
    friends,
    gamesettings,
    helpdesk,
    jobs,
    modpacks,
    mods,
    players,
    pushalerts,
    recommendations,
    schedules,
    security,
    server,
    server_settings,
    servertypes,
    settings,
    system,
    transfer,
    updates,
    world,
)
from .settings import SETTABLE_PREFIXES

LEGACY_PER_SERVER = (server, console, players, mods, backups, schedules)
PER_SERVER = (
    *LEGACY_PER_SERVER,
    server_settings,
    recommendations,
    servertypes,
    gamesettings,
    duplicate,
    modpacks,
    friends,
    chat,
    world,
)
GLOBAL = (
    auth,
    accounts,
    settings,
    security,
    system,
    jobs,
    pushalerts,
    files,
    transfer,
    helpdesk,
    updates,
)
MODULES = (*GLOBAL, *PER_SERVER)
SERVER_PREFIX = "/servers/{server_id}"

router = APIRouter(prefix="/api")
for module in GLOBAL:
    router.include_router(module.router)
# Server types and versions are agent-wide (the comparison table, each
# type's version list, creating a server) as well as per server.
router.include_router(servertypes.global_router)
# Reading a modpack and making a new server from it are agent-wide too.
router.include_router(modpacks.global_router)
# A helper limited to some servers is refused the others' routes here, once,
# rather than in each route.
for module in PER_SERVER:
    router.include_router(
        module.router, prefix=SERVER_PREFIX, dependencies=[Depends(server_access)]
    )
for module in LEGACY_PER_SERVER:
    router.include_router(module.router, dependencies=[Depends(mark_alias), Depends(server_access)])


def api_routes() -> list[tuple[str, APIRoute, str]]:
    """Every API route as it is served: (full path, route, scope), where scope
    is "global", "server" (under /api/servers/{server_id}) or "alias" (a
    per-server route also served unprefixed for the first server). Read from
    the routers themselves, so a new route is never missed by the tests that
    walk them (permissions declared, helpers refused)."""
    found: list[tuple[str, APIRoute, str]] = []
    globals_ = [m.router for m in GLOBAL] + [servertypes.global_router, modpacks.global_router]
    for global_router in globals_:
        for route in global_router.routes:
            if isinstance(route, APIRoute):
                found.append((f"/api{route.path}", route, "global"))
    for module in PER_SERVER:
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                found.append((f"/api{SERVER_PREFIX}{route.path}", route, "server"))
    for module in LEGACY_PER_SERVER:
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                found.append((f"/api{route.path}", route, "alias"))
    return found


__all__ = ["MODULES", "PER_SERVER", "SERVER_PREFIX", "SETTABLE_PREFIXES", "api_routes", "router"]
