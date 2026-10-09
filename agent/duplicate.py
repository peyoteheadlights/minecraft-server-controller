"""Duplicating a server: a new server with the same software, add-ons,
config files and game settings.

The new server gets its own name, folder, color (the next one no server
uses) and port (a free one from the port manager), and with crossplay on
its own Bedrock port. Its world is either a copy of the current one or a
fresh one, which Minecraft makes on the new server's first start (with a
new seed: the copied level-seed is cleared).

Safety:

  * the new folder is checked with check_new_server_folder (empty or new,
    not a system folder, overlapping no other server or this app's own
    folders), and every file is written through check_archive_member,
    so nothing lands outside it
  * only the source server's own folder is read; links are never followed,
    and the agent's data, logs, crash reports and kept copies of old
    versions are left behind
  * the source is never read while Minecraft is writing to it: a running
    server is told to save and pause saving ("save-off") for the copy and
    to carry on afterwards, and a server that is starting or stopping is
    refused
  * it runs as a job on the source server, so no backup or other change
    runs on it at the same time, and through the safe-change routine
    (change, then check the copy). A copy that fails or doesn't check out
    is removed again, and the new server comes off the list
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import PROJECT_ROOT
from .events import Event
from .jobs import Job
from .minecraft import properties
from .safechange import SafeChange, SafeChangeError, run_safe_change
from .security.paths import check_archive_member, check_new_server_folder, is_inside
from .servertypes.create import new_server_id
from .servertypes.install import INSTALL_LOG, PREVIOUS

if TYPE_CHECKING:
    from .core import AgentCore, ServerContext
    from .jobs import JobHandle

log = logging.getLogger("msc.duplicate")

WORLD_CHOICES = ("copy", "fresh")
# Never copied: what belongs to the old server's history rather than to
# its set-up, and the Java process's lock on the world.
LEFT_BEHIND = frozenset(
    {
        "logs",
        "crash-reports",
        "debug",
        "mcsc-data",
        PREVIOUS,
        INSTALL_LOG,
        "session.lock",
        ".fabric",
    }
)


class DuplicateError(RuntimeError):
    """The server can't be duplicated as asked. Written for people."""


def world_folders(directory: Path, server_type: Any = None) -> set[str]:
    """The folders that make up the world (see properties.world_folders)."""
    return properties.world_folders(directory, server_type)


def files_to_copy(ctx: ServerContext, world: str) -> list[tuple[Path, str, int]]:
    """(source file, path inside the folder, size) for everything copied."""
    return walk_source(ctx, world)[0]


def walk_source(ctx: ServerContext, world: str) -> tuple[list[tuple[Path, str, int]], list[str]]:
    """The files to copy, and every folder (paths inside the server folder)
    so that empty ones such as mods/ are made in the copy too."""
    source = ctx.config.server_dir
    skip_top = set(LEFT_BEHIND)
    if world == "fresh":
        skip_top |= world_folders(source, ctx.config.server_type)
    # The app's own folders, when someone keeps them inside the server
    # folder (backups, the data folder), stay behind too.
    inside = [
        p
        for p in (ctx.config.data_dir, ctx.config.backup_dir, ctx.config.log_dir)
        if p and is_inside(source, p) and Path(p).resolve() != source.resolve()
    ]
    found: list[tuple[Path, str, int]] = []
    folders: list[str] = []
    for root, dirs, names in os.walk(source, followlinks=False):
        here = Path(root)
        relative_root = here.relative_to(source)
        top_level = relative_root == Path(".")
        kept_dirs = []
        for name in dirs:
            full = here / name
            if os.path.islink(full):
                continue
            if top_level and (name in skip_top or ".replaced-" in name):
                continue
            if any(is_inside(p, full) for p in inside):
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs
        folders.extend((relative_root / name).as_posix() for name in kept_dirs)
        for name in names:
            full = here / name
            if full.is_symlink():
                continue
            if top_level and (name in skip_top or name.startswith(".")):
                continue
            if name == "session.lock" or name.endswith(".part"):
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            found.append((full, (relative_root / name).as_posix(), size))
    return found, folders


def _copy_files(
    files: list[tuple[Path, str, int]], target: Path, advance, folders: Sequence[str] = ()
) -> tuple[int, int]:
    copied = size = 0
    for relative in folders:
        check_archive_member(target, relative).mkdir(parents=True, exist_ok=True)
    for source, relative, length in files:
        destination = check_archive_member(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
        size += length
        advance(length)
    return copied, size


def _check_copy(files: list[tuple[Path, str, int]], target: Path) -> tuple[bool, str]:
    for _source, relative, length in files:
        path = target / relative
        if not path.is_file():
            return False, f"{relative} is missing from the copy"
        if path.stat().st_size != length:
            return False, f"{relative} is {path.stat().st_size} bytes, expected {length}"
    return True, f"{len(files)} file(s) copied and checked"


def _prepare_properties(target: Path, port: int, name: str, world: str) -> None:
    path = target / properties.FILENAME
    edited = properties.PropertiesFile.read(path) if path.is_file() else properties.PropertiesFile()
    edited.set("server-port", str(port))
    if world == "fresh" and (edited.get("level-seed") or "").strip():
        edited.set("level-seed", "")
    if not path.is_file():
        edited.set("motd", name[:59])
    edited.write(path)


def _entry_for_copy(ctx: ServerContext, folder: Path) -> dict[str, Any]:
    """The source's config entry, for the copy. A folder setting written as
    a full path (mods, mod backups, mod trash, backups) would point the copy
    at the source's own folder, so the two would share mods or backups:
    one inside the source's folder is moved to the same place in the copy,
    and any other is dropped so the copy uses its own default."""
    entry = ctx.config.root.server_entry(ctx.server_id)
    source = ctx.config.server_dir
    for section in ("mods", "backups"):
        settings = entry.get(section)
        if not isinstance(settings, dict):
            continue
        for key in [k for k in settings if k == "directory" or k.endswith("_directory")]:
            value = settings[key]
            if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
                continue
            path = Path(value).expanduser()
            if is_inside(source, path) and path.resolve() != source.resolve():
                settings[key] = str(folder / path.resolve().relative_to(source.resolve()))
            else:
                del settings[key]
        if not settings:
            del entry[section]
    return entry


def check_request(
    core: AgentCore, ctx: ServerContext, name: str, directory: str, world: str
) -> tuple[str, Path]:
    name = (name or "").strip()
    if not name:
        raise DuplicateError("Give the new server a name.")
    if world not in WORLD_CHOICES:
        raise DuplicateError("Choose whether to copy the world or start a fresh one.")
    if not ctx.config.server_dir_configured or not ctx.config.server_dir.is_dir():
        raise DuplicateError(f"{ctx.name}'s folder isn't there, so it can't be copied.")
    if ctx.server.held_by:
        raise DuplicateError(f"Wait for '{ctx.server.held_by}' to finish first.")
    state = ctx.server.state.value
    if ctx.server.running and state != "ONLINE":
        raise DuplicateError(
            f"{ctx.name} is {state.lower().replace('_', ' ')}. Wait until it is running or "
            "stopped, then try again."
        )
    registered = [(other.name, other.config.server_dir) for other in core.servers.values()]
    folder = check_new_server_folder(
        directory, protected=[PROJECT_ROOT, core.config.data_dir], registered=registered
    )
    return name, folder


async def start_duplicate(
    core: AgentCore,
    ctx: ServerContext,
    *,
    name: str,
    directory: str,
    world: str,
    user: str = "system",
) -> Job:
    """Check the request, then copy in the background as a job."""
    name, folder = check_request(core, ctx, name, directory, world)
    port = core.ports.suggest()
    if port is None:
        raise DuplicateError("No free port was found for the new server.")
    bedrock = core.ports.suggest_bedrock() if ctx.config.server.crossplay else None
    if ctx.config.server.crossplay and bedrock is None:
        raise DuplicateError("No free port was found for the new server's Bedrock players.")
    new_id = new_server_id(name, core.config.server_ids)
    existed = folder.is_dir()
    title = f"Duplicating {ctx.name} as {name}"

    async def run(job: JobHandle) -> dict[str, Any]:
        job.step("Finding the files to copy")
        files, folders = await asyncio.to_thread(walk_source, ctx, world)
        total = sum(size for _, _, size in files)

        async def copy(handle: JobHandle | None) -> dict[str, Any]:
            paused = held = False
            if not ctx.server.running:
                # Nothing (a click, a schedule, another device) may start
                # the source while its files are being read.
                if ctx.server.held_by:
                    raise DuplicateError(f"Wait for '{ctx.server.held_by}' to finish first.")
                ctx.server.held_by = title
                held = True
            if ctx.server.running:
                # Minecraft writes the world in the background. Save it all
                # now and pause saving, so the copy is of a still world.
                job.step("Saving the world and pausing saves")
                await ctx.server.send_command("save-all flush", internal=True)
                await asyncio.sleep(3)
                await ctx.server.send_command("save-off", internal=True)
                paused = True
                await asyncio.sleep(1)
            try:
                job.step("Copying files", total=total, unit="bytes")
                folder.mkdir(parents=True, exist_ok=True)
                copied, size = await asyncio.to_thread(
                    _copy_files, files, folder, job.advance, folders
                )
            finally:
                if held:
                    ctx.server.held_by = None
                if paused:
                    try:
                        await ctx.server.send_command("save-on", internal=True)
                    except Exception:  # pragma: no cover - logged, never hidden
                        log.warning("could not turn saving back on", exc_info=True)
            return {"files": copied, "size_bytes": size}

        async def check(result: dict[str, Any]) -> tuple[bool, str]:
            return await asyncio.to_thread(_check_copy, files, folder)

        plan = SafeChange(
            title=title, change=copy, check=check, stop_server=False, take_backup=False
        )
        registered = False
        try:
            outcome = await run_safe_change(ctx.server, ctx.backups, plan, job=job, user=user)
            job.step("Setting up the new server")
            await asyncio.to_thread(_prepare_properties, folder, port, name, world)
            entry = _entry_for_copy(ctx, folder)
            entry.update(id=new_id, name=name, directory=str(folder), port=port)
            if bedrock:
                entry["bedrock_port"] = bedrock
            new_ctx = await core.add_server(entry, user=user)
            registered = True
            # Its color is the next one no server uses, picked as it joins
            # the list; the software record follows the source's.
            row = core.db.server_row(ctx.server_id) or {}
            core.db.set_server_software(new_id, ctx.config.server.type, row.get("loader"))
            if bedrock:
                from .crossplay import write_geyser_config

                await asyncio.to_thread(write_geyser_config, new_ctx, bedrock)
        except BaseException as exc:
            if registered:
                try:
                    await core.remove_server(new_id, user=user)
                except Exception:  # pragma: no cover - reported, never hidden
                    log.exception("could not take the half-made copy off the list")
            if not existed:
                shutil.rmtree(folder, ignore_errors=True)
            if isinstance(exc, SafeChangeError):
                raise DuplicateError(f"The copy didn't work: {exc}") from exc
            raise
        await new_ctx.bus.publish(
            Event(
                type="server_duplicated",
                level="success",
                message=f"Made {name} as a copy of {ctx.name}"
                + (" with a copy of its world" if world == "copy" else " with a fresh world"),
                data={
                    "source": ctx.server_id,
                    "source_name": ctx.name,
                    "server_name": name,
                    "world": world,
                    "files": outcome["files"],
                    "port": port,
                    "bedrock_port": bedrock,
                    "check": outcome["check"],
                },
            )
        )
        core.db.audit(
            "server_duplicate",
            user=user,
            target=new_id,
            detail=f"from {ctx.server_id}, world {world}",
            server_id=new_id,
        )
        return {
            "server_id": new_id,
            "name": name,
            "directory": str(folder),
            "port": port,
            "bedrock_port": bedrock,
            "world": world,
            "files": outcome["files"],
            "size_bytes": outcome["size_bytes"],
            "check": outcome["check"],
            "finished_at": time.time(),
        }

    return core.jobs.start("duplicate", title, run, server_id=ctx.server_id, risky=True, user=user)


def suggestion(core: AgentCore, ctx: ServerContext) -> dict[str, Any]:
    """A name and a folder for the copy, next to the source's folder. Only
    suggestions: the person can change both."""
    base = f"{ctx.name} copy"
    taken = {other.name.lower() for other in core.servers.values()}
    name, number = base, 2
    while name.lower() in taken:
        name = f"{base} {number}"
        number += 1
    parent = ctx.config.server_dir.parent
    folder = parent / name
    number = 2
    while folder.exists():
        folder = parent / f"{name} {number}"
        number += 1
    return {
        "name": name,
        "directory": str(folder),
        "running": ctx.server.running,
        "crossplay": bool(ctx.config.server.crossplay),
        "world_folders": sorted(world_folders(ctx.config.server_dir, ctx.config.server_type))
        if ctx.config.server_dir.is_dir()
        else [],
    }
