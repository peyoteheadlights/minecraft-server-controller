"""Bringing a single-player world in, and taking a server's world out.

Import: a world arrives either as a ``.zip`` dropped on the page or as a
folder on the PC (usually one in ``%APPDATA%\\.minecraft\\saves``, picked
with the folder picker). Before anything changes, the app reads it and
shows what it is: the name inside its level.dat, the Minecraft version that
last saved it, and its size. A world without a level.dat is refused, and a
zip is read through the same zip-slip check every extraction uses
(``check_archive_member``). The import itself runs through the safe-change
routine: the server must be stopped, the current world is backed up and
checked first, and that backup is the one-click undo.

Download: the server's world as a ``.zip`` laid out the way single-player
Minecraft expects (one folder with level.dat, DIM-1 and DIM1 inside), so it
can be dropped into the saves folder and played offline. Paper and Purpur
keep the Nether and the End in folders of their own; both directions
convert between the two layouts (ServerType.split_dimensions).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .events import Event
from .minecraft import nbt
from .minecraft.properties import FILENAME, PropertiesFile, world_folder
from .safechange import SafeChange, run_safe_change
from .security.paths import (
    PathSafetyError,
    assert_not_symlink,
    check_archive_member,
    directory_size,
    zip_member_is_symlink,
)

if TYPE_CHECKING:
    from .core import ServerContext
    from .jobs import JobHandle

log = logging.getLogger("msc.worldimport")

UPLOAD_FOLDER = "world-uploads"
DOWNLOAD_FOLDER = "world-downloads"
KEEP_SECONDS = 24 * 3600
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_ZIP_BYTES = 20 * 1024**3
MAX_UNPACKED_BYTES = 40 * 1024**3
MAX_MEMBERS = 500_000
# Files the game holds open or that belong to one PC, never copied.
SKIP_FILES = {"session.lock"}
DIMENSIONS = {"DIM-1": "_nether", "DIM1": "_the_end"}


class WorldImportError(RuntimeError):
    pass


@dataclass
class WorldInfo:
    """What is shown before a world replaces anything."""

    source: str  # "zip" or "folder"
    folder_name: str  # the world's folder name in the zip or on disk
    name: str | None  # LevelName from level.dat
    version: str | None  # the Minecraft version that last saved it
    last_played: float | None
    size_bytes: int
    files: int
    read_problem: str | None = None  # level.dat present but unreadable

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# reading a world before anything changes
# ----------------------------------------------------------------------
def _level(data: bytes) -> tuple[dict[str, Any], str | None]:
    try:
        return nbt.level_info(data), None
    except nbt.NbtError as exc:
        return {"name": None, "version": None, "last_played": None}, str(exc)


def _zip_root(names: list[str]) -> str:
    """The folder inside the zip that holds the world: the one level.dat at
    the shallowest depth. "" means the zip's top level is the world."""
    found = []
    for name in names:
        parts = [p for p in name.replace("\\", "/").split("/") if p]
        if not parts or parts[0] == "__MACOSX" or parts[-1] != "level.dat":
            continue
        found.append(parts[:-1])
    if not found:
        raise WorldImportError(
            "This isn't a Minecraft world: there is no level.dat in it. Zip the world's own "
            "folder (the one with level.dat inside)."
        )
    depth = min(len(p) for p in found)
    shallowest = {"/".join(p) for p in found if len(p) == depth}
    if len(shallowest) > 1:
        raise WorldImportError("This zip holds more than one world. Zip just the one you want.")
    if depth > 2:
        raise WorldImportError("The world is buried too deep inside the zip to be the one meant.")
    return shallowest.pop()


def inspect_zip(path: Path) -> tuple[WorldInfo, str]:
    """Read a world zip. Returns what it is and the folder inside the zip
    that holds it. Raises WorldImportError for anything that isn't a world
    or isn't safe to extract."""
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise WorldImportError("That zip is bigger than 20 GB, so it wasn't read.")
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise WorldImportError("That zip has far too many files in it to be a world.")
            check_base = path.parent / "zip-check"
            for info in infos:
                try:
                    check_archive_member(check_base, info.filename, zip_member_is_symlink(info))
                except PathSafetyError as exc:
                    raise WorldImportError(f"That zip isn't safe to open: {exc}") from exc
            root = _zip_root([i.filename for i in infos])
            prefix = f"{root}/" if root else ""
            members = [i for i in infos if i.filename.startswith(prefix) and not i.is_dir()]
            size = sum(i.file_size for i in members)
            if size > MAX_UNPACKED_BYTES:
                raise WorldImportError("That world unpacks to more than 40 GB, so it wasn't used.")
            level = zf.getinfo(f"{prefix}level.dat")
            if level.file_size > nbt.MAX_UNCOMPRESSED:
                raise WorldImportError("That world's level.dat is far too big to be real.")
            info, problem = _level(zf.read(level))
    except zipfile.BadZipFile as exc:
        raise WorldImportError(f"That file isn't a zip that can be opened: {exc}") from exc
    folder = root.split("/")[-1] if root else path.stem
    return (
        WorldInfo(
            source="zip",
            folder_name=folder[:100],
            name=info["name"],
            version=info["version"],
            last_played=info["last_played"],
            size_bytes=size,
            files=len(members),
            read_problem=problem,
        ),
        root,
    )


def inspect_folder(value: str) -> tuple[WorldInfo, Path]:
    """Read a world folder on the PC."""
    raw = (value or "").strip()
    if not raw or "\0" in raw:
        raise WorldImportError("Choose the world's folder.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise WorldImportError("Choose the whole path to the world's folder.")
    try:
        assert_not_symlink(path)
    except PathSafetyError as exc:
        raise WorldImportError(str(exc)) from exc
    if not path.is_dir():
        raise WorldImportError(f"{path} isn't there, or isn't a folder.")
    level = path / "level.dat"
    if not level.is_file():
        raise WorldImportError(
            f"{path} isn't a Minecraft world: there is no level.dat in it. Choose the world's "
            "own folder, inside saves."
        )
    if level.stat().st_size > nbt.MAX_COMPRESSED:
        raise WorldImportError("That world's level.dat is far too big to be real.")
    info, problem = _level(level.read_bytes())
    files = sum(len(names) for _, _, names in os.walk(path))
    return (
        WorldInfo(
            source="folder",
            folder_name=path.name[:100],
            name=info["name"],
            version=info["version"],
            last_played=info["last_played"],
            size_bytes=directory_size(path),
            files=files,
            read_problem=problem,
        ),
        path.resolve(),
    )


def saves_folder() -> Path | None:
    """Single-player Minecraft's own saves folder on this PC, if there is one."""
    appdata = os.environ.get("APPDATA")
    candidates = [Path(appdata) / ".minecraft" / "saves"] if appdata else []
    candidates.append(Path.home() / ".minecraft" / "saves")
    for folder in candidates:
        if folder.is_dir():
            return folder
    return None


def saved_worlds() -> list[dict[str, Any]]:
    """The worlds in the saves folder, newest first: folder and name only
    (each one is read in full when it's picked)."""
    folder = saves_folder()
    if folder is None:
        return []
    found = []
    for entry in folder.iterdir():
        try:
            if entry.is_symlink() or not (entry / "level.dat").is_file():
                continue
            found.append(
                {
                    "folder": entry.name,
                    "path": str(entry),
                    "modified": (entry / "level.dat").stat().st_mtime,
                }
            )
        except OSError:
            continue
    return sorted(found, key=lambda w: w["modified"], reverse=True)[:100]


# ----------------------------------------------------------------------
# uploads and picked folders, held until the person confirms
# ----------------------------------------------------------------------
def _folder(ctx_or_core: Any, name: str) -> Path:
    core = getattr(ctx_or_core, "core", ctx_or_core)
    folder = core.config.data_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _clean(folder: Path) -> None:
    now = time.time()
    for old in folder.iterdir():
        try:
            if now - old.stat().st_mtime > KEEP_SECONDS:
                old.unlink()
        except OSError:
            pass


def new_upload(core: Any) -> tuple[str, Path]:
    folder = _folder(core, UPLOAD_FOLDER)
    _clean(folder)
    token = secrets.token_hex(16)
    return token, folder / f"{token}.zip"


def remember_folder(core: Any, path: Path) -> str:
    folder = _folder(core, UPLOAD_FOLDER)
    _clean(folder)
    token = secrets.token_hex(16)
    (folder / f"{token}.json").write_text(json.dumps({"folder": str(path)}), encoding="utf-8")
    return token


def _ticket(core: Any, token: str) -> tuple[str, Path]:
    if not TOKEN_RE.match(token or ""):
        raise WorldImportError("That world isn't known. Choose it again.")
    folder = _folder(core, UPLOAD_FOLDER)
    upload = folder / f"{token}.zip"
    if upload.is_file():
        return "zip", upload
    picked = folder / f"{token}.json"
    if picked.is_file():
        data = json.loads(picked.read_text(encoding="utf-8"))
        return "folder", Path(data["folder"])
    raise WorldImportError("That world isn't there any more. Choose it again.")


def forget(core: Any, token: str) -> None:
    if TOKEN_RE.match(token or ""):
        folder = _folder(core, UPLOAD_FOLDER)
        for suffix in (".zip", ".json"):
            (folder / f"{token}{suffix}").unlink(missing_ok=True)


def describe(core: Any, token: str) -> WorldInfo:
    kind, path = _ticket(core, token)
    return inspect_zip(path)[0] if kind == "zip" else inspect_folder(str(path))[0]


# ----------------------------------------------------------------------
# putting a world in place
# ----------------------------------------------------------------------
def _world_names(ctx: ServerContext) -> tuple[str, list[str]]:
    """The server's world folder name (level-name) and every folder that
    belongs to its world, existing or not."""
    props = ctx.config.server_dir / FILENAME
    values = PropertiesFile.read(props).values() if props.is_file() else {}
    name = world_folder(ctx.config.server_dir, values).name
    return name, [name, f"{name}_nether", f"{name}_the_end"]


def _target_for(relative: str, world: str, split: bool) -> str | None:
    """Where a file of a single-player world goes in this server's folder.
    None: not copied."""
    parts = [p for p in relative.replace("\\", "/").split("/") if p]
    if not parts or parts[-1] in SKIP_FILES:
        return None
    if split and parts[0] in DIMENSIONS:
        # Paper and Purpur keep each dimension in a folder of its own.
        return "/".join([world + DIMENSIONS[parts[0]], *parts])
    return "/".join([world, *parts])


def _move_aside(base: Path, folders: list[str]) -> list[str]:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    for name in folders:
        live = base / name
        if live.exists():
            retired = base / f"{name}.replaced-{stamp}"
            number = 2
            while retired.exists():
                retired = base / f"{name}.replaced-{stamp}-{number}"
                number += 1
            shutil.move(str(live), str(retired))
            moved.append(str(retired))
    return moved


def _put_back(base: Path, moved: list[str]) -> None:
    for retired in moved:
        path = Path(retired)
        name = path.name.split(".replaced-")[0]
        if (base / name).exists():
            shutil.rmtree(base / name, ignore_errors=True)
        if path.exists():
            shutil.move(str(path), str(base / name))


def _extract(
    kind: str,
    source: Path,
    root: str,
    base: Path,
    world: str,
    split: bool,
    job: JobHandle | None,
) -> int:
    """Copy the world's files into place. Every destination is checked to
    stay inside the server folder, the same check backups use."""
    written = 0
    if kind == "zip":
        prefix = f"{root}/" if root else ""
        with zipfile.ZipFile(source) as zf:
            members = [i for i in zf.infolist() if i.filename.startswith(prefix) and not i.is_dir()]
            if job:
                job.step("Copying the world in", total=len(members), unit="files")
            for info in members:
                relative = info.filename[len(prefix) :]
                target = _target_for(relative, world, split)
                if target is None:
                    continue
                destination = check_archive_member(base, target, zip_member_is_symlink(info))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(destination, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                written += 1
                if job:
                    job.advance(1)
        return written
    files = []
    for folder, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(folder, d))]
        for name in names:
            full = Path(folder) / name
            if not full.is_symlink():
                files.append(full)
    if job:
        job.step("Copying the world in", total=len(files), unit="files")
    for full in files:
        relative = full.relative_to(source).as_posix()
        target = _target_for(relative, world, split)
        if target is None:
            continue
        destination = check_archive_member(base, target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, destination)
        written += 1
        if job:
            job.advance(1)
    return written


async def import_world(ctx: ServerContext, token: str, user: str = "system") -> dict[str, Any]:
    """Replace this server's world with the uploaded or picked one, through
    the safe-change routine. The server has to be stopped first."""
    if ctx.server.running:
        raise WorldImportError(
            f"Stop {ctx.name} first. A running server would write over the world being put in."
        )
    kind, source = _ticket(ctx.core, token)
    if kind == "zip":
        info, root = await asyncio.to_thread(inspect_zip, source)
    else:
        info, source = await asyncio.to_thread(inspect_folder, str(source))
        root = ""
    base = ctx.config.server_dir
    world, folders = _world_names(ctx)
    existing = [name for name in folders if (base / name).exists()]
    split = ctx.config.server_type.split_dimensions
    moved: list[str] = []
    title = f"Importing the world {info.name or info.folder_name}"

    async def change(job: JobHandle | None) -> dict[str, Any]:
        if job:
            job.step("Moving the current world aside")
        moved.extend(await asyncio.to_thread(_move_aside, base, folders))
        try:
            written = await asyncio.to_thread(_extract, kind, source, root, base, world, split, job)
        except BaseException:
            await asyncio.to_thread(_put_back, base, moved)
            raise
        return {"files": written, "moved_aside": moved}

    async def check(result: dict[str, Any]) -> tuple[bool, str]:
        level = base / world / "level.dat"
        if not level.is_file():
            return False, "the new world has no level.dat"
        if result["files"] == 0:
            return False, "no files were copied"
        return True, f"{result['files']} files in place, level.dat present"

    plan = SafeChange(
        title=title,
        change=change,
        check=check,
        take_backup=bool(existing),
        backup_name="pre-import",
        backup_note=f"Automatic safety copy before importing {info.name or info.folder_name}",
        backup_includes=existing or None,
        # A failed import puts the moved-aside world back itself.
        undo_on_change_error=False,
    )

    async def run(job: JobHandle | None) -> dict[str, Any]:
        result = await run_safe_change(ctx.server, ctx.backups, plan, job=job, user=user)
        # The checked safety backup is the undo, so the old world's folders
        # moved aside are not kept as well (they would double its disk use).
        for retired in moved:
            await asyncio.to_thread(shutil.rmtree, retired, True)
        return result

    created, result = await ctx.core.jobs.run(
        "world_import", f"{title} into {ctx.name}", run, server_id=ctx.server_id, risky=True, user=user
    )
    forget(ctx.core, token)
    ctx.db.audit("world_import", user=user, target=info.name or info.folder_name)
    await ctx.bus.publish(
        Event(
            type="world_imported",
            level="success",
            message=f"Imported the world {info.name or info.folder_name}",
            data={"world": info.to_dict(), "undo": result.get("undo")},
        )
    )
    return {"job_id": created.id, "world": info.to_dict(), **result}


# ----------------------------------------------------------------------
# downloading a server's world for single-player
# ----------------------------------------------------------------------
def _download_members(base: Path, world: str, split: bool) -> list[tuple[Path, str]]:
    """Every file of the world and the name it gets in the zip, laid out
    for single-player: one folder, with DIM-1 and DIM1 inside."""
    out: list[tuple[Path, str]] = []
    sources = [(base / world, "")]
    if split:
        for dim, suffix in DIMENSIONS.items():
            sources.append((base / f"{world}{suffix}" / dim, dim))
    for folder, inside in sources:
        if not folder.is_dir():
            continue
        for root, dirs, names in os.walk(folder, followlinks=False):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            for name in names:
                full = Path(root) / name
                if name in SKIP_FILES or full.is_symlink():
                    continue
                relative = full.relative_to(folder).as_posix()
                out.append((full, f"{world}/{inside + '/' if inside else ''}{relative}"))
    return out


def _zip_world(target: Path, members: list[tuple[Path, str]], job: JobHandle | None) -> int:
    if job:
        job.step("Packing the world", total=len(members), unit="files")
    written = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for full, name in members:
            try:
                zf.write(full, name)
                written += 1
            except OSError as exc:
                log.warning("skipping %s: %s", full, exc)
            if job:
                job.advance(1)
    return written


async def prepare_download(ctx: ServerContext, user: str = "system") -> dict[str, Any]:
    """Pack the world into a zip for single-player, as a job. While the
    server runs, Minecraft is asked to save and to pause saving, as for a
    backup, so the zip holds a consistent world."""
    base = ctx.config.server_dir
    world, _ = _world_names(ctx)
    if not (base / world / "level.dat").is_file():
        raise WorldImportError("This server has no world yet. Start it once to make one.")
    split = ctx.config.server_type.split_dimensions
    folder = _folder(ctx.core, DOWNLOAD_FOLDER)
    _clean(folder)
    token = secrets.token_hex(16)
    target = folder / f"{token}.zip"

    async def run(job: JobHandle) -> dict[str, Any]:
        paused = False
        server = ctx.server
        if server.running and server.state.value == "ONLINE":
            try:
                await server.send_command("save-all flush", internal=True)
                await asyncio.sleep(3)
                await server.send_command("save-off", internal=True)
                paused = True
            except Exception:
                log.warning("could not pause saving for the world download", exc_info=True)
        try:
            members = await asyncio.to_thread(_download_members, base, world, split)
            files = await asyncio.to_thread(_zip_world, target, members, job)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            if paused:
                try:
                    await server.send_command("save-on", internal=True)
                except Exception:
                    log.warning("could not turn saving back on", exc_info=True)
        return {"token": token, "files": files, "size_bytes": target.stat().st_size}

    _, result = await ctx.core.jobs.run(
        "world_download",
        f"Packing {ctx.name}'s world",
        run,
        server_id=ctx.server_id,
        risky=True,
        user=user,
    )
    safe = re.sub(r"[^A-Za-z0-9 ._-]+", "", ctx.name).strip() or "world"
    return {**result, "filename": f"{safe} world.zip"}


def download_path(core: Any, token: str) -> Path:
    if not TOKEN_RE.match(token or ""):
        raise WorldImportError("That download isn't known. Pack the world again.")
    path = _folder(core, DOWNLOAD_FOLDER) / f"{token}.zip"
    if not path.is_file():
        raise WorldImportError("That download isn't there any more. Pack the world again.")
    return path
