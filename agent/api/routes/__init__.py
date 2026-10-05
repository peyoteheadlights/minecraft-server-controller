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

from ..deps import mark_alias
from . import (
    auth,
    backups,
    console,
    duplicate,
    friends,
    gamesettings,
    jobs,
    modpacks,
    mods,
    players,
    recommendations,
    schedules,
    security,
    server,
    server_settings,
    servertypes,
    settings,
    system,
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
)
GLOBAL = (auth, settings, security, system, jobs)
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
for module in PER_SERVER:
    router.include_router(module.router, prefix=SERVER_PREFIX)
for module in LEGACY_PER_SERVER:
    router.include_router(module.router, dependencies=[Depends(mark_alias)])

__all__ = ["MODULES", "PER_SERVER", "SERVER_PREFIX", "SETTABLE_PREFIXES", "router"]
