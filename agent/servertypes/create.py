"""Creating a brand-new server from scratch.

The "+" tab's New server panel ends here. The order matters, and nothing
is written until the step before it has passed:

  1. check the folder (empty or new, not a system folder, no overlap with
     another server or with this app's own folders)
  2. check Java: a version Minecraft needs must already be installed, or
     the person is told what to install before anything is downloaded
  3. make the folder and write server.properties with sensible defaults and
     a free port from the port manager
  4. write eula.txt with eula=false, and eula=true only when the person
     has ticked the box themselves (``eula_accepted``). The agent never
     accepts Minecraft's rules on their behalf.
  5. download and set the server software up through the safe downloader
     and the job tracker
  6. register the server, so the dashboard shows it

The server is not started: its version stays Unknown until its own console
reports it, and "ready" means the console said it started.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from .. import colors, servertypes
from ..config import PROJECT_ROOT, check_server_id
from ..security.paths import check_new_server_folder
from .install import InstallError, install_plan
from .versions import list_versions, make_plan

if TYPE_CHECKING:
    from ..core import AgentCore
    from ..jobs import JobHandle

log = logging.getLogger("msc.servertypes.create")

EULA_URL = "https://aka.ms/MinecraftEULA"
TEMURIN_URL = "https://adoptium.net/temurin/releases/"

# What a new server's server.properties says. Everything else is left to
# Minecraft's own defaults, written on its first start.
DEFAULT_PROPERTIES: dict[str, str] = {
    "motd": "A Minecraft server",
    "max-players": "20",
    "online-mode": "true",
    "difficulty": "normal",
    "gamemode": "survival",
    "pvp": "true",
    "spawn-protection": "0",
    "view-distance": "10",
    "simulation-distance": "10",
    "enable-command-block": "false",
    "white-list": "false",
}
# Memory for a new server, from the PC's real RAM. Phase 6 adds the slider.
MIN_MEMORY_MB = 2048
MAX_DEFAULT_MEMORY_MB = 8192


def default_memory_mb() -> tuple[int, str]:
    """How much memory to give a new server, and why, from measured RAM."""
    try:
        total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:  # pragma: no cover - psutil is always there in practice
        return MIN_MEMORY_MB, "This PC's memory couldn't be read, so 2 GB is used."
    # Half the PC's memory, between 2 and 8 GB, so Windows and the browser
    # keep enough.
    chosen = max(MIN_MEMORY_MB, min(MAX_DEFAULT_MEMORY_MB, (total_mb // 2 // 512) * 512))
    return chosen, f"Half of this PC's {total_mb // 1024} GB of memory, up to 8 GB."


def new_server_id(name: str, taken: list[str]) -> str:
    import re

    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "server"
    if not base[0].isalnum():
        base = f"server-{base}"
    candidate, number = base, 2
    lowered = {t.lower() for t in taken}
    while candidate in lowered:
        candidate = f"{base}-{number}"
        number += 1
    return check_server_id(candidate)


def write_properties(
    directory: Path, port: int, name: str, extra: dict[str, str] | None = None
) -> Path:
    """Write server.properties with this app's defaults and the given port."""
    values = {**DEFAULT_PROPERTIES, "motd": name[:59], "server-port": str(int(port))}
    values.update(extra or {})
    lines = [
        "# Written by Minecraft Server Control when this server was created.",
        f"# {time.strftime('%Y-%m-%d %H:%M:%S')}",
        *(f"{key}={value}" for key, value in sorted(values.items())),
    ]
    path = directory / "server.properties"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_eula(directory: Path, accepted: bool) -> Path:
    """Write eula.txt. ``eula=true`` is written only when the person has
    accepted Minecraft's rules themselves."""
    path = directory / "eula.txt"
    path.write_text(
        "# Minecraft's rules (the EULA): "
        + EULA_URL
        + "\n"
        + (
            "# You accepted them in Minecraft Server Control on "
            + time.strftime("%Y-%m-%d %H:%M:%S")
            + "\n"
            if accepted
            else "# Not accepted yet. The server will not start until it says eula=true.\n"
        )
        + f"eula={'true' if accepted else 'false'}\n",
        encoding="utf-8",
    )
    return path


def java_problem(minecraft: str, java_executable: str = "java") -> dict[str, Any] | None:
    """Why this version can't be run with the Java installed now, or None.
    Unknown (Java not detected) is reported, never treated as fine."""
    from .. import appinfo
    from ..minecraft.java import check_compatibility, detect_java, required_java

    info = detect_java(java_executable)
    needed = required_java(minecraft)
    verdict = check_compatibility(info, minecraft)
    # Installed copies install Java with their setup, on the PC.
    how = (
        f' (open "{appinfo.SETUP_SHORTCUT}" from the PC\'s Start menu)'
        if appinfo.installed()
        else ""
    )
    if verdict["verdict"] == "incompatible":
        return {
            "problem": (
                f"Minecraft {minecraft} needs Java {needed} or newer, but this PC has Java "
                f"{info.version_major}. Install Java {needed} first{how}, then try again."
            ),
            "required": needed,
            "installed": info.version_major,
            "download": TEMURIN_URL,
        }
    if info.version_major is None:
        return {
            "problem": (
                "Java couldn't be found on this PC, so a Minecraft server can't run yet. "
                f"Install Java {needed or 21} first{how}, then try again."
            ),
            "required": needed,
            "installed": None,
            "download": TEMURIN_URL,
        }
    return None


async def options(core: AgentCore) -> dict[str, Any]:
    """What the New server panel needs: the types, the default memory, the
    next free port and color, and Minecraft's rules link."""
    memory_mb, memory_reason = default_memory_mb()
    return {
        "types": servertypes.catalog(),
        "recommended": servertypes.RECOMMENDED,
        "memory_mb": memory_mb,
        "memory_reason": memory_reason,
        "port": core.ports.suggest() or 25565,
        "color": colors.next_unused(ctx.color for ctx in core.servers.values()),
        "palette": colors.palette(),
        "eula_url": EULA_URL,
        "java_download": TEMURIN_URL,
        "java": core.default.server.java_info.to_dict() if core.default.server.java_info else None,
    }


async def create_server(
    core: AgentCore,
    *,
    name: str,
    directory: str,
    type_id: str,
    minecraft: str,
    loader: str | None = None,
    memory_mb: int | None = None,
    color: str | None = None,
    eula_accepted: bool = False,
    user: str = "system",
    after_install: Callable[[Any, Path, Any], Awaitable[dict[str, Any]]] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Create a new server. Returns the new server's summary and the job.

    ``after_install`` (used by modpack import) runs inside the same job
    once the software is in place, with the new ServerContext, its folder
    and the job; what it returns is added to the result. If it fails, the
    server is taken off the list and its folder removed like any other
    failed creation."""
    from ..events import Event

    server_type = servertypes.get(type_id)
    name = (name or "").strip()
    if not name:
        raise InstallError("Give the new server a name.")
    if not eula_accepted:
        raise InstallError(
            "Minecraft's rules (the EULA) have to be accepted before a server can be "
            "created. Tick the box to accept them."
        )
    registered = [(ctx.name, ctx.config.server_dir) for ctx in core.servers.values()]
    folder = check_new_server_folder(
        directory, protected=[PROJECT_ROOT, core.config.data_dir], registered=registered
    )
    versions = await list_versions(server_type.id)
    entry = next((v for v in versions if v.minecraft == minecraft), None)
    if entry is None:
        raise InstallError(f"{server_type.name} doesn't offer Minecraft {minecraft}.")
    problem = java_problem(minecraft, core.config.server.java)
    if problem:
        raise InstallError(problem["problem"])

    plan = await make_plan(server_type.id, minecraft, loader)
    server_id = new_server_id(name, core.config.server_ids)
    port = core.ports.suggest() or 25565
    memory = int(memory_mb or default_memory_mb()[0])
    if not MIN_MEMORY_MB // 2 <= memory <= 1024 * 64:
        raise InstallError("That amount of memory isn't a sensible size for a server.")

    existed = folder.is_dir()
    title = title or f"Creating {name} ({server_type.name} {minecraft})"

    async def run(job: JobHandle | None) -> dict[str, Any]:
        if job:
            job.step("Making the server's folder")
        folder.mkdir(parents=True, exist_ok=True)
        created_here = True
        try:
            if server_type.content_folder:
                (folder / server_type.content_folder).mkdir(exist_ok=True)
            write_properties(folder, port, name)
            write_eula(folder, eula_accepted)
            entry_config = {
                "id": server_id,
                "name": name,
                "directory": str(folder),
                "type": server_type.id,
                "jar": plan.jar or server_type.jar,
                "args_file": "",
                "java": core.config.server.java,
                "jvm_args": [f"-Xmx{memory}M"],
                "port": port,
            }
            # A ServerContext is needed to install (the install log and the
            # data folder belong to the server), so register it first and
            # take it off the list again if the install fails.
            ctx = await core.add_server(entry_config, user=user)
        except Exception:
            if created_here and not existed:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        try:
            result = await install_plan(ctx, plan, folder, job=job)
            ctx.config.set("server.jar", result["jar"])
            ctx.config.set("server.args_file", result["args_file"])
            if server_type.content_folder:
                ctx.config.set("mods.directory", server_type.content_folder)
            ctx.config.save()
            core.db.set_server_software(server_id, server_type.id, result["loader_version"])
            if color:
                core.db.set_server_color(server_id, colors.normalise(color))
            ctx.server.pending_version = {
                "type": server_type.id,
                "minecraft_version": minecraft,
                "loader_version": result["loader_version"],
                "since": time.time(),
            }
            extra = await after_install(ctx, folder, job) if after_install else {}
        except Exception:
            # Leave nothing half-made: the server comes off the list and
            # the folder this app created goes with it.
            try:
                await core.remove_server(server_id, user=user)
            except Exception:  # pragma: no cover - reported, never hidden
                log.exception("could not take the half-created server off the list")
            if not existed:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        await ctx.bus.publish(
            Event(
                type="server_created",
                level="success",
                message=(
                    f"Created {name} as {server_type.name} {minecraft}. Start it to finish "
                    "setting it up."
                ),
                data={
                    "server_name": name,
                    "type": server_type.id,
                    "minecraft_version": minecraft,
                    "directory": str(folder),
                    "verified": result["verified"],
                },
            )
        )
        return {
            **result,
            **extra,
            "server_id": server_id,
            "name": name,
            "directory": str(folder),
            "port": port,
            "memory_mb": memory,
            "eula_accepted": True,
        }

    job, result = await core.jobs.run(
        "server_create", title, run, server_id=None, risky=False, user=user
    )
    ctx = core.get_server(server_id)
    core.db.audit(
        "server_create",
        user=user,
        target=server_id,
        detail=f"{server_type.id} {minecraft}",
        server_id=server_id,
    )
    return {
        **result,
        "job_id": job.id,
        "server": ctx.summary(),
        "next": (
            "Press Start on the new server. It counts as ready once its console says it "
            "has started."
        ),
    }
