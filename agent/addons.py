"""Bedrock add-ons: behavior packs and resource packs.

A Bedrock server takes add-ons as packs, not as mods. They arrive as:

  * ``.mcpack``: one pack (a zip with manifest.json at its top, or in one
    folder inside it)
  * ``.mcaddon``: several packs, as ``.mcpack`` files or pack folders
  * ``.mctemplate``: a world template; the packs inside it are installed
    (its world can be imported on the World page)

Before anything is written, every pack is read and checked:

  * every zip entry passes the zip-slip check every extraction uses, links
    are refused, and sizes are capped
  * its manifest.json must be readable JSON (Mojang's own files have
    ``//`` comments, which are allowed), with a header that has a valid
    UUID and version, and modules that each have a valid UUID and a type
  * a pack with ``data`` or ``script`` modules goes into behavior_packs/, one
    with ``resources`` into resource_packs/. Skin packs and anything else
    are refused, saying why

Then each pack is unpacked into a new folder and only moved into place
once it is complete. Packs are turned on per world by adding them to the
world's ``world_behavior_packs.json`` or ``world_resource_packs.json``. The
server reads those when it starts, so a change made while it runs takes
effect after a restart, and the page says so.

Nothing here downloads anything (Bedrock add-ons aren't on Modrinth) or
runs anything: packs are data the server reads.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import uuid as uuid_module
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .minecraft.properties import FILENAME, PropertiesFile, world_folder
from .security.paths import PathSafetyError, check_archive_member, zip_member_is_symlink

if TYPE_CHECKING:
    from .core import ServerContext

log = logging.getLogger("msc.addons")

SUFFIXES = (".mcpack", ".mcaddon", ".mctemplate")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024**3
MAX_MEMBERS = 100_000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_NESTED_PACK_BYTES = 300 * 1024 * 1024
FOLDERS = {"behavior": "behavior_packs", "resource": "resource_packs"}
WORLD_FILES = {"behavior": "world_behavior_packs.json", "resource": "world_resource_packs.json"}
MODULE_KINDS = {
    "data": "behavior",
    "script": "behavior",
    "javascript": "behavior",
    "client_data": "behavior",
    "resources": "resource",
}
INSTALLED_KEY = "bedrock_addons"
REMOVED_FOLDER = "removed-addons"
# Archive paths are checked against a folder that is never written to.
CHECK_BASE = Path("/archive-check")


class AddonError(RuntimeError):
    """Written for the person reading it."""


@dataclass
class Pack:
    uuid: str
    version: str
    name: str
    description: str | None
    kind: str  # "behavior" or "resource"
    folder: str  # e.g. behavior_packs/MyPack_1a2b3c4d
    enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def version_list(self) -> list[int]:
        return [int(n) for n in self.version.split(".")]


# ----------------------------------------------------------------------
# reading a manifest
# ----------------------------------------------------------------------
def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments outside strings (Mojang's manifests
    have them)."""
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _uuid(value: Any, where: str) -> str:
    try:
        return str(uuid_module.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise AddonError(f"The pack's manifest.json has no valid UUID {where}.") from None


def _version(value: Any, where: str) -> str:
    """[1, 0, 0] (or "1.0.0" in newer manifests) as "1.0.0"."""
    if isinstance(value, str) and re.fullmatch(r"\d{1,9}\.\d{1,9}\.\d{1,9}(?:[-+][\w.]+)?", value):
        return value.split("-")[0].split("+")[0]
    if (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n < 10**9 for n in value)
    ):
        return ".".join(str(n) for n in value)
    raise AddonError(f"The pack's manifest.json has no valid version {where}.")


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:limit] or None


def read_manifest(data: bytes) -> dict[str, Any]:
    """Check a manifest.json. Returns uuid, version, name, description and
    kind, or raises AddonError saying what is wrong."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise AddonError("The pack's manifest.json is far too big to be one.")
    try:
        manifest = json.loads(_strip_comments(data.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError):
        raise AddonError("The pack's manifest.json isn't valid JSON.") from None
    if not isinstance(manifest, dict):
        raise AddonError("The pack's manifest.json isn't valid JSON.")
    header = manifest.get("header")
    if not isinstance(header, dict):
        raise AddonError("The pack's manifest.json has no header.")
    pack_uuid = _uuid(header.get("uuid"), "in its header")
    version = _version(header.get("version"), "in its header")
    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules:
        raise AddonError("The pack's manifest.json lists no modules.")
    kinds = set()
    for module in modules:
        if not isinstance(module, dict):
            raise AddonError("The pack's manifest.json has a module that isn't readable.")
        _uuid(module.get("uuid"), "for one of its modules")
        _version(module.get("version"), "for one of its modules")
        module_type = str(module.get("type") or "").lower()
        if module_type == "skin_pack":
            raise AddonError("That is a skin pack. Skins are chosen by players, not servers.")
        if module_type == "world_template":
            kinds.add("world_template")
            continue
        if module_type not in MODULE_KINDS:
            raise AddonError(
                f"The pack's manifest.json has a module of a type this app doesn't know "
                f"('{module_type[:30]}')."
            )
        kinds.add(MODULE_KINDS[module_type])
    kinds.discard("world_template")
    if not kinds:
        return {"uuid": pack_uuid, "version": version, "kind": "world_template"}
    if len(kinds) > 1:
        raise AddonError(
            "The pack's manifest.json mixes behavior and resource modules, which Bedrock "
            "doesn't allow in one pack."
        )
    return {
        "uuid": pack_uuid,
        "version": version,
        "name": _text(header.get("name"), 80) or "Unnamed pack",
        "description": _text(header.get("description"), 300),
        "kind": kinds.pop(),
    }


# ----------------------------------------------------------------------
# reading an upload
# ----------------------------------------------------------------------
@dataclass
class Found:
    """One pack in an upload: its manifest and where its files are."""

    manifest: dict[str, Any]
    archive: bytes  # the zip it is in (the upload itself, or a nested .mcpack)
    prefix: str  # its folder inside that zip ("" for the top)


def _check_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise AddonError("That file has far too many files in it to be an add-on.")
    total = 0
    for info in infos:
        try:
            check_archive_member(CHECK_BASE, info.filename, zip_member_is_symlink(info))
        except PathSafetyError as exc:
            raise AddonError(f"That file isn't safe to open: {exc}") from None
        total += info.file_size
    if total > MAX_UNPACKED_BYTES:
        raise AddonError("That add-on unpacks to more than 2 GB, so it wasn't used.")
    return infos


def _packs_in(data: bytes, depth: int = 0) -> list[Found]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AddonError("That file isn't an add-on that can be opened (it isn't a zip).") from None
    found: list[Found] = []
    with zf:
        infos = _check_members(zf)
        names = [i.filename.replace("\\", "/") for i in infos]
        manifests = sorted(
            (n for n in names if n.rsplit("/", 1)[-1] == "manifest.json"),
            key=lambda n: n.count("/"),
        )
        roots: list[str] = []
        for name in manifests:
            prefix = name[: -len("manifest.json")]
            if prefix.startswith("__MACOSX/"):
                continue
            # A pack's own subfolders can't hold another pack's manifest.
            if any(prefix.startswith(root) and root != prefix for root in roots):
                continue
            if prefix.count("/") > 2:
                continue
            info = zf.getinfo(name)
            if info.file_size > MAX_MANIFEST_BYTES:
                raise AddonError("A pack's manifest.json is far too big to be one.")
            manifest = read_manifest(zf.read(info))
            # A .mctemplate's own manifest (the world template) is at its
            # top, and its packs are in folders below it, so it can't hide
            # them the way a pack's subfolders are hidden.
            if manifest["kind"] != "world_template":
                roots.append(prefix)
            found.append(Found(manifest, data, prefix))
        if depth == 0:
            for info in infos:
                if info.filename.lower().endswith(".mcpack") and not info.is_dir():
                    if info.file_size > MAX_NESTED_PACK_BYTES:
                        raise AddonError("A pack inside that add-on is far too big.")
                    found.extend(_packs_in(zf.read(info), depth + 1))
    return found


def read_upload(filename: str, data: bytes) -> list[Found]:
    """Every pack in an uploaded .mcpack, .mcaddon or .mctemplate, each
    checked. Raises AddonError for anything that isn't one or isn't safe."""
    if not filename.lower().endswith(SUFFIXES):
        raise AddonError("Choose a Bedrock add-on: a .mcpack, .mcaddon or .mctemplate file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AddonError("That add-on is bigger than 500 MB, so it wasn't read.")
    found = [f for f in _packs_in(data) if f.manifest["kind"] != "world_template"]
    if not found:
        raise AddonError("No behavior or resource pack was found in that file.")
    seen: set[str] = set()
    for item in found:
        if item.manifest["uuid"] in seen:
            raise AddonError("That add-on holds the same pack twice.")
        seen.add(item.manifest["uuid"])
    return found


# ----------------------------------------------------------------------
# what is installed
# ----------------------------------------------------------------------
def _installed(ctx: ServerContext) -> dict[str, dict[str, Any]]:
    value = ctx.db.get_setting(INSTALLED_KEY)
    return dict(value) if isinstance(value, dict) else {}


def world_path(ctx: ServerContext) -> Path:
    path = ctx.config.server_dir / FILENAME
    values = PropertiesFile.read(path).values() if path.is_file() else {}
    return world_folder(ctx.config.server_dir, values, ctx.config.server_type)


def _read_world_list(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise AddonError(
            f"{path.name} in the world folder isn't valid JSON, so it wasn't changed. Fix or "
            "delete it first."
        ) from None
    if not isinstance(data, list):
        raise AddonError(f"{path.name} in the world folder isn't a list, so it wasn't changed.")
    return [entry for entry in data if isinstance(entry, dict)]


def _write_json(path: Path, value: Any) -> None:
    temp = path.with_name(f".{path.name}.part")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def enabled_ids(ctx: ServerContext) -> set[str]:
    world = world_path(ctx)
    found: set[str] = set()
    for name in WORLD_FILES.values():
        try:
            entries = _read_world_list(world / name)
        except AddonError:
            continue
        found.update(str(e.get("pack_id") or "").lower() for e in entries)
    return found


def _pack_from_folder(ctx: ServerContext, relative: str) -> Pack | None:
    folder = ctx.config.server_dir / relative
    manifest = folder / "manifest.json"
    try:
        info = read_manifest(manifest.read_bytes())
    except (OSError, AddonError):
        return None
    if info["kind"] not in FOLDERS:
        return None
    return Pack(
        uuid=info["uuid"],
        version=info["version"],
        name=info["name"],
        description=info["description"],
        kind=info["kind"],
        folder=relative,
    )


def list_packs(ctx: ServerContext) -> list[Pack]:
    """The packs someone added (Mojang's built-in packs are left out), each
    read from its own manifest.json, and whether this world has it on."""
    from .servertypes import bedrock

    shipped = set((bedrock.shipped_record(ctx) or {}).get("packs", []))
    known = {entry.get("folder") for entry in _installed(ctx).values()}
    on = enabled_ids(ctx)
    packs = []
    for kind, folder_name in FOLDERS.items():
        root = ctx.config.server_dir / folder_name
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            relative = f"{folder_name}/{entry.name}"
            if not entry.is_dir() or entry.is_symlink() or relative in shipped:
                continue
            # Without a record of Mojang's files (a server added by folder),
            # only packs this app installed are listed.
            if not shipped and relative not in known:
                continue
            pack = _pack_from_folder(ctx, relative)
            if pack and pack.kind == kind:
                pack.enabled = pack.uuid in on
                packs.append(pack)
    return packs


def _folder_name(name: str, pack_uuid: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:40] or "pack"
    return f"{slug}_{pack_uuid[:8]}"


# ----------------------------------------------------------------------
# installing, turning on and off, removing
# ----------------------------------------------------------------------
def _unpack(found: Found, target: Path) -> int:
    written = 0
    with zipfile.ZipFile(io.BytesIO(found.archive)) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith(found.prefix) or info.is_dir():
                continue
            relative = name[len(found.prefix) :]
            if not relative:
                continue
            destination = check_archive_member(target, relative, zip_member_is_symlink(info))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(destination, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            written += 1
    return written


def install(ctx: ServerContext, filename: str, data: bytes, enable: bool = True) -> dict[str, Any]:
    """Install every pack in an upload, and turn each on in this world when
    ``enable``. A pack already installed is replaced by the new copy."""
    found = read_upload(filename, data)
    base = ctx.config.server_dir
    record = _installed(ctx)
    current = {p.uuid: p for p in list_packs(ctx)}
    installed: list[Pack] = []
    for item in found:
        info = item.manifest
        kind = info["kind"]
        old = current.get(info["uuid"])
        relative = (
            old.folder if old else f"{FOLDERS[kind]}/{_folder_name(info['name'], info['uuid'])}"
        )
        target = base / relative
        staging = target.with_name(f".{target.name}.part")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            if _unpack(item, staging) == 0:
                raise AddonError(f"The pack {info['name']} has no files.")
            if not (staging / "manifest.json").is_file():
                raise AddonError(f"The pack {info['name']} has no manifest.json at its top.")
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if target.exists():
            _set_aside(ctx, target)
        staging.rename(target)
        record[info["uuid"]] = {"folder": relative, "installed_at": time.time()}
        pack = Pack(
            uuid=info["uuid"],
            version=info["version"],
            name=info["name"],
            description=info["description"],
            kind=kind,
            folder=relative,
        )
        installed.append(pack)
    ctx.db.set_setting(INSTALLED_KEY, record)
    if enable:
        for pack in installed:
            set_enabled(ctx, pack.uuid, True, packs=[*list_packs(ctx)])
        on = enabled_ids(ctx)
        for pack in installed:
            pack.enabled = pack.uuid in on
    return {"installed": [p.to_dict() for p in installed], **after(ctx)}


def set_enabled(
    ctx: ServerContext, pack_uuid: str, enabled: bool, packs: list[Pack] | None = None
) -> dict[str, Any]:
    """Turn a pack on or off in this server's world."""
    wanted = _uuid(pack_uuid, "")
    pack = next((p for p in (packs or list_packs(ctx)) if p.uuid == wanted), None)
    if pack is None:
        raise AddonError("That pack isn't installed on this server.")
    world = world_path(ctx)
    if not world.is_dir():
        raise AddonError(
            "This server's world hasn't been made yet. Start the server once so it creates "
            "its world, then turn the pack on."
        )
    path = world / WORLD_FILES[pack.kind]
    entries = _read_world_list(path)
    kept = [e for e in entries if str(e.get("pack_id") or "").lower() != wanted]
    if enabled:
        kept.append({"pack_id": wanted, "version": pack.version_list})
    if kept != entries:
        _write_json(path, kept)
    return after(ctx)


def _set_aside(ctx: ServerContext, folder: Path) -> Path:
    """Move a pack folder into the data folder rather than deleting it."""
    keep = ctx.config.data_dir / REMOVED_FOLDER / time.strftime("%Y%m%d-%H%M%S")
    keep.mkdir(parents=True, exist_ok=True)
    target = keep / f"{folder.parent.name}-{folder.name}"
    number = 2
    while target.exists():
        target = keep / f"{folder.parent.name}-{folder.name}-{number}"
        number += 1
    shutil.move(str(folder), str(target))
    return target


def remove(ctx: ServerContext, pack_uuid: str) -> dict[str, Any]:
    """Turn a pack off and move it out of the server folder (into the data
    folder's removed-addons, so it can be put back by hand)."""
    wanted = _uuid(pack_uuid, "")
    pack = next((p for p in list_packs(ctx) if p.uuid == wanted), None)
    if pack is None:
        raise AddonError("That pack isn't installed on this server.")
    if world_path(ctx).is_dir():
        set_enabled(ctx, wanted, False)
    kept = _set_aside(ctx, ctx.config.server_dir / pack.folder)
    record = _installed(ctx)
    record.pop(wanted, None)
    ctx.db.set_setting(INSTALLED_KEY, record)
    return {"removed": pack.to_dict(), "kept_at": str(kept), **after(ctx)}


def after(ctx: ServerContext) -> dict[str, Any]:
    running = bool(ctx.server.running)
    return {"running": running, "restart_needed": running}


def view(ctx: ServerContext) -> dict[str, Any]:
    world = world_path(ctx)
    return {
        "addons": [p.to_dict() for p in list_packs(ctx)],
        "world": world.name if world.is_dir() else None,
        "running": bool(ctx.server.running),
        "restart_needed": None,
    }
