"""REST API, one router per area.

Every route except /api/health and /api/auth/login requires a bearer token.
No route accepts a filesystem path, a shell string or a command line: the
only free text that reaches the operating system is a Minecraft console
command, and that is validated by agent.minecraft.commands first.

The routers are grouped by scope. PER_SERVER routers act on one Minecraft
server; when the agent manages several, they move under
/api/servers/{server_id}/. GLOBAL routers are about the agent itself.
"""

from fastapi import APIRouter

from . import auth, backups, console, mods, players, schedules, security, server, settings, system
from .settings import SETTABLE_PREFIXES

PER_SERVER = (server, console, players, mods, backups, schedules)
GLOBAL = (auth, settings, security, system)
MODULES = (*GLOBAL, *PER_SERVER)

router = APIRouter(prefix="/api")
for module in MODULES:
    router.include_router(module.router)

__all__ = ["MODULES", "SETTABLE_PREFIXES", "router"]
