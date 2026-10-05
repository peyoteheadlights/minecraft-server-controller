"""Letting Bedrock players join: Geyser and Floodgate.

Geyser translates between Bedrock and Java, and Floodgate lets Bedrock
players in without a Java account (``auth-type: floodgate``). Both are
downloaded from GeyserMC's official download API through the safe
downloader (agent/downloads.py), and only for the server types GeyserMC
publishes a build for (read from the type's capabilities, so a type with no
build never shows the switch).

Geyser listens on a UDP port of its own, picked by the port manager and
checked as UDP. Turning crossplay off moves both files aside rather than
deleting them, so turning it back on keeps their settings.

What differs for Bedrock players is said plainly in the dashboard, not
glossed over: custom menus and some resource packs behave differently, and
consoles (Xbox, PlayStation, Switch) cannot join over Tailscale at all.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import downloads
from .downloads import DownloadError, FileSpec

if TYPE_CHECKING:
    from .core import ServerContext
    from .jobs import JobHandle

log = logging.getLogger("msc.crossplay")

GEYSER_API = "https://download.geysermc.org/v2/projects"
# Geyser's own default Bedrock port, and what Minecraft Bedrock tries first.
DEFAULT_BEDROCK_PORT = 19132
# Floodgate's default: Bedrock players appear as ".Name".
USERNAME_PREFIX = "."
DISABLED_SUFFIX = ".disabled"


class CrossplayError(RuntimeError):
    """Crossplay could not be set up. The message is for the person."""


def available(ctx: ServerContext) -> bool:
    """Whether GeyserMC publishes a build for this server's type."""
    return ctx.config.server_type.crossplay


def _folder(ctx: ServerContext) -> Path:
    """Where Geyser and Floodgate live: this server's mods or plugins
    folder, which is what the server itself loads from."""
    server_type = ctx.config.server_type
    if not server_type.has_content:
        raise CrossplayError(
            f"{server_type.name} servers can't load Geyser, so Bedrock players can't join "
            "one. Change the server type to Fabric, NeoForge or Paper first."
        )
    folder = ctx.config.mods_dir
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _names(ctx: ServerContext) -> tuple[str, str]:
    """The file names this app gives Geyser and Floodgate (never taken from
    the download's own answer)."""
    platform = ctx.config.server_type.geyser_platform or ""
    return f"Geyser-{platform}.jar", f"floodgate-{platform}.jar"


def installed(ctx: ServerContext) -> dict[str, Any]:
    """What is actually on disk, read from disk."""
    if not ctx.config.server_type.has_content:
        return {"geyser": None, "floodgate": None, "folder": None}
    folder = ctx.config.mods_dir
    geyser, floodgate = _names(ctx)
    found: dict[str, Any] = {}
    for key, name in (("geyser", geyser), ("floodgate", floodgate)):
        path = folder / name
        aside = folder / (name + DISABLED_SUFFIX)
        found[key] = (
            {"file": name, "size": path.stat().st_size, "enabled": True}
            if path.is_file()
            else {"file": aside.name, "size": aside.stat().st_size, "enabled": False}
            if aside.is_file()
            else None
        )
    found["folder"] = str(folder)
    return found


async def _latest(platform: str, project: str) -> FileSpec:
    """The newest build of Geyser or Floodgate for this platform, with the
    checksum GeyserMC publishes for it."""
    data = await downloads.fetch_json(f"{GEYSER_API}/{project}")
    builds = data.get("versions") if isinstance(data, dict) else None
    latest = await downloads.fetch_json(f"{GEYSER_API}/{project}/versions/latest/builds/latest")
    if not isinstance(latest, dict):
        raise CrossplayError(f"GeyserMC's {project} download list couldn't be read.")
    downloads_block = (latest.get("downloads") or {}).get(platform)
    if not downloads_block:
        raise CrossplayError(
            f"GeyserMC doesn't publish {project} for {platform} servers, so Bedrock "
            "players can't join this one."
        )
    version = str(latest.get("version") or (builds[-1] if builds else "latest"))
    build = str(latest.get("build") or "latest")
    url = f"{GEYSER_API}/{project}/versions/{version}/builds/{build}/downloads/{platform}"
    return FileSpec(
        url=downloads.check_url(url),
        name=f"{'Geyser' if project == 'geyser' else 'floodgate'}-{platform}.jar",
        sha256=downloads_block.get("sha256"),
        allow_unverified=True,  # GeyserMC publishes sha256 for most builds
    )


def write_geyser_config(ctx: ServerContext, port: int) -> Path:
    """Geyser's config: the Bedrock port it listens on, and Floodgate for
    sign-in so Bedrock players need no Java account."""
    folder = _folder(ctx).parent / "config" / "Geyser-Fabric"
    server_type = ctx.config.server_type
    if server_type.content == "plugins":
        folder = _folder(ctx) / "Geyser-Spigot"
    folder.mkdir(parents=True, exist_ok=True)
    java_port = ctx.core.ports.port_of(ctx).port
    path = folder / "config.yml"
    path.write_text(
        "\n".join(
            [
                "# Written by Minecraft Server Control.",
                f"# {time.strftime('%Y-%m-%d %H:%M:%S')}",
                "bedrock:",
                "  address: 0.0.0.0",
                f"  port: {int(port)}",
                "  clone-remote-port: false",
                "remote:",
                "  address: 127.0.0.1",
                f"  port: {int(java_port)}",
                # Bedrock players join without a Java account.
                "  auth-type: floodgate",
                "  use-proxy-protocol: false",
                f'username-prefix: "{USERNAME_PREFIX}"',
                "passthrough-motd: true",
                "passthrough-player-counts: true",
                "config-version: 4",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


async def enable(
    ctx: ServerContext, port: int | None = None, user: str = "system"
) -> dict[str, Any]:
    """Install Geyser and Floodgate and switch crossplay on. Runs as a job
    and needs the server stopped, like any change to its files."""
    from .events import Event

    server_type = ctx.config.server_type
    if not available(ctx):
        raise CrossplayError(
            f"GeyserMC has no build for {server_type.name}, so Bedrock players can't join "
            "this server. Fabric, NeoForge, Paper and Purpur can."
        )
    platform = server_type.geyser_platform or ""
    folder = _folder(ctx)
    if ctx.server.running:
        raise CrossplayError(
            "Stop the server first: Geyser is added to the server's files, and the server "
            "keeps them open while it runs."
        )
    chosen = int(port) if port else (ctx.core.ports.suggest_bedrock() or DEFAULT_BEDROCK_PORT)
    clash = ctx.core.ports.bedrock_owner(chosen, exclude=ctx.server_id)
    if clash:
        raise CrossplayError(
            f"Port {chosen} is already used for Bedrock by '{clash}'. Pick another one."
        )

    async def run(job: JobHandle | None) -> dict[str, Any]:
        files = []
        try:
            for project in ("geyser", "floodgate"):
                if job:
                    job.step(f"Downloading {project.capitalize()}")
                spec = await _latest(platform, project)
                aside = folder / (spec.name + DISABLED_SUFFIX)
                if aside.is_file():
                    aside.unlink()  # replaced by the new download
                fetched = await downloads.download(spec, folder, job=job)
                files.append({**fetched.to_dict(), "project": project})
        except DownloadError as exc:
            for entry in files:
                (folder / entry["file"]).unlink(missing_ok=True)
            raise CrossplayError(str(exc)) from exc
        if job:
            job.step("Writing Geyser's settings")
        config = write_geyser_config(ctx, chosen)
        ctx.config.set("server.crossplay", True)
        ctx.config.set("server.bedrock_port", chosen)
        ctx.config.save()
        # "downloaded" rather than "files": status() reports the files that
        # are in place, and the two must not overwrite each other.
        return {"downloaded": files, "config": str(config), "port": chosen}

    job, result = await ctx.core.jobs.run(
        "crossplay",
        f"Letting Bedrock players join {ctx.name}",
        run,
        server_id=ctx.server_id,
        risky=True,
        user=user,
    )
    ctx.core.db.audit(
        "crossplay_on", user=user, target=ctx.server_id, detail=str(chosen), server_id=ctx.server_id
    )
    await ctx.bus.publish(
        Event(
            type="crossplay_enabled",
            level="success",
            message=(f"Bedrock players can join {ctx.name} on port {chosen} once it starts again."),
            data={"port": chosen, "files": [f["file"] for f in result["downloaded"]]},
        )
    )
    return {**result, "job_id": job.id, **status(ctx)}


async def disable(ctx: ServerContext, user: str = "system") -> dict[str, Any]:
    """Switch crossplay off: both files are moved aside, not deleted."""
    from .events import Event

    if ctx.server.running:
        raise CrossplayError(
            "Stop the server first: Geyser is part of the server's files, and the server "
            "keeps them open while it runs."
        )
    folder = ctx.config.mods_dir
    moved = []
    for name in _names(ctx):
        path = folder / name
        if path.is_file():
            target = folder / (name + DISABLED_SUFFIX)
            if target.exists():
                target.unlink()
            shutil.move(str(path), str(target))
            moved.append(target.name)
    ctx.config.set("server.crossplay", False)
    ctx.config.save()
    ctx.core.db.audit("crossplay_off", user=user, target=ctx.server_id, server_id=ctx.server_id)
    await ctx.bus.publish(
        Event(
            type="crossplay_disabled",
            level="warn",
            message=f"Bedrock players can no longer join {ctx.name}",
            data={"moved_aside": moved},
        )
    )
    return {"moved_aside": moved, **status(ctx)}


def is_bedrock_name(username: str, prefix: str = USERNAME_PREFIX) -> bool:
    """Whether a name carries Floodgate's Bedrock prefix. The name itself
    is always shown as it is; a Bedrock player's Java name is never guessed."""
    return bool(prefix) and str(username or "").startswith(prefix)


def status(ctx: ServerContext) -> dict[str, Any]:
    """Everything the dashboard shows about crossplay for this server."""
    server_type = ctx.config.server_type
    on = bool(ctx.config.server.crossplay)
    port = int(ctx.config.server.bedrock_port or 0) or None
    files = installed(ctx)
    return {
        "available": server_type.crossplay,
        "unavailable_reason": None
        if server_type.crossplay
        else f"GeyserMC publishes no build for {server_type.name} servers.",
        "enabled": on,
        "port": port,
        "protocol": "udp",
        "default_port": DEFAULT_BEDROCK_PORT,
        "username_prefix": USERNAME_PREFIX,
        "files": files,
        # Only a fact when both files are really there and the switch is on.
        "ready": bool(on and files.get("geyser") and files.get("floodgate")),
        "differences": [
            "Bedrock players see some things differently: custom menus and some resource "
            "packs don't work the same way.",
            "Xbox, PlayStation and Switch can't join a server over Tailscale. Phones, "
            "tablets and Windows Bedrock can.",
        ],
    }
