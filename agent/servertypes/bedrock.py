"""Mojang's Bedrock Dedicated Server: where it comes from, and putting it in
place.

Where it comes from. Mojang's download links service (the one the
minecraft.net download page reads) names one zip per platform, and only the
newest version. Mojang publishes no checksum for it. So:

  * the zip is fetched through the safe downloader (HTTPS, the host
    allow-list in agent/downloads.py) and recorded as **unverified**, never
    as checked (house rule 1)
  * the SHA-256 of what arrived is written to the install log, and kept in
    an index next to the zip, so a later download of the same version can
    be compared with it
  * every zip the app downloads is kept in the data folder
    (``bedrock-versions``), so going back to an earlier version, or rolling
    a change back, works for every version this app has downloaded. Older
    versions are only available if they were kept here; the page says so.
  * the download page asks people to accept Mojang's EULA and Privacy
    Policy, so nothing is downloaded until the person has ticked that they
    accept both. The acceptance is recorded with who ticked it and when.

Putting it in place. The zip holds the program and Mojang's own files
(including the built-in packs in behavior_packs/ and resource_packs/). An
update replaces only those: worlds/, server.properties, allowlist.json,
permissions.json and every pack someone added stay exactly as they are.
What was replaced is moved into the data folder first, keeping its folder
layout, so the change can be rolled back in one click.

Nothing here runs the program. It is started by the process supervisor
from the server's folder, as an argument list with no shell (the
download-and-run exception in docs/security.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import downloads
from ..downloads import DownloadError, FileSpec
from ..security.paths import PathSafetyError, check_archive_member, zip_member_is_symlink

if TYPE_CHECKING:
    from ..core import ServerContext
    from ..jobs import JobHandle
    from .versions import Plan, Version

log = logging.getLogger("msc.servertypes.bedrock")

LINKS_URL = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
# The links service names each download; this is the Windows server's.
# (Linux is used only when the agent itself runs on Linux, as in tests.)
DOWNLOAD_TYPE = "serverBedrockWindows" if os.name == "nt" else "serverBedrockLinux"
EULA_URL = "https://www.minecraft.net/eula"
PRIVACY_URL = "https://go.microsoft.com/fwlink/?LinkId=521839"
ZIP_RE = re.compile(r"/bedrock-server-(?P<version>\d+(?:\.\d+){1,3})\.zip$")
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
KEPT_FOLDER = "bedrock-versions"
INDEX = "index.json"
# What an update never replaces: the worlds and the server's own settings.
KEEP = frozenset({"worlds", "server.properties", "allowlist.json", "permissions.json"})
PACK_FOLDERS = ("behavior_packs", "resource_packs")
TERMS_KEY = "bedrock_terms"
SHIPPED_KEY = "bedrock_shipped"
MAX_ZIP_BYTES = 400 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024

_kept_root: Path | None = None
# Archive paths are checked against a folder that is never written to:
# only whether a path would leave it matters before unpacking.
CHECK_BASE = Path("/archive-check")


class BedrockError(RuntimeError):
    """Written for the person reading it."""


def configure(data_dir: Path) -> None:
    """Called by the agent at start: the zips are kept in its data folder."""
    global _kept_root
    _kept_root = Path(data_dir) / KEPT_FOLDER


def kept_root() -> Path:
    if _kept_root is not None:
        return _kept_root
    from ..config import default_data_root

    return default_data_root() / KEPT_FOLDER


# ----------------------------------------------------------------------
# the terms
# ----------------------------------------------------------------------
def terms(db) -> dict[str, Any] | None:
    """Who accepted Mojang's EULA and Privacy Policy, and when, or None."""
    value = db.get_setting(TERMS_KEY)
    return value if isinstance(value, dict) and value.get("accepted") else None


def accept_terms(db, user: str) -> dict[str, Any]:
    record = {
        "accepted": True,
        "user": user,
        "at": time.time(),
        "eula": EULA_URL,
        "privacy": PRIVACY_URL,
    }
    db.set_setting(TERMS_KEY, record)
    db.audit("bedrock_terms_accepted", user=user, detail="Minecraft EULA and Privacy Policy")
    return record


def require_terms(db) -> None:
    if terms(db) is None:
        raise BedrockError(
            "Mojang's EULA and Privacy Policy have to be accepted before the Bedrock server "
            "can be downloaded. Tick the box to accept them."
        )


# ----------------------------------------------------------------------
# the versions: the newest from Mojang, plus every one kept here
# ----------------------------------------------------------------------
async def latest() -> tuple[str, str]:
    """The newest version and its download address, from Mojang's links
    service. The version is read from the file name in that address."""
    data = await downloads.fetch_json(LINKS_URL)
    links = ((data or {}).get("result") or {}).get("links") if isinstance(data, dict) else None
    if not isinstance(links, list):
        raise DownloadError("Mojang's download list couldn't be read.")
    for entry in links:
        if isinstance(entry, dict) and entry.get("downloadType") == DOWNLOAD_TYPE:
            url = downloads.check_url(str(entry.get("downloadUrl") or ""))
            match = ZIP_RE.search(url)
            if not match:
                raise DownloadError(
                    "Mojang's download list names a file this app doesn't recognise, so "
                    "nothing was downloaded."
                )
            return match.group("version"), url
    raise DownloadError("Mojang's download list has no Bedrock server for Windows right now.")


def _index(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / INDEX).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def kept_versions(root: Path | None = None) -> list[dict[str, Any]]:
    """Every version kept here whose zip is still there, newest first."""
    from .versions import version_key

    root = root or kept_root()
    found = []
    for version, entry in _index(root).items():
        if not VERSION_RE.match(version) or not isinstance(entry, dict):
            continue
        if (root / f"bedrock-server-{version}.zip").is_file():
            found.append({**entry, "version": version})
    return sorted(found, key=lambda e: version_key(e["version"]), reverse=True)


def _record_kept(root: Path, version: str, entry: dict[str, Any]) -> None:
    index = _index(root)
    index[version] = entry
    temp = root / f".{INDEX}.part"
    temp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    os.replace(temp, root / INDEX)


async def versions() -> tuple[list[Version], str | None]:
    """The versions that can be installed: Mojang's newest, and every one
    kept here. The second value says why Mojang's list couldn't be read,
    when it couldn't (the kept ones are still offered)."""
    from .versions import Version, version_key

    kept = {entry["version"]: entry for entry in kept_versions()}
    problem = None
    newest = None
    try:
        newest, _url = await latest()
    except DownloadError as exc:
        if not kept:
            raise
        # The reason goes to the log; the dashboard gets a fixed sentence,
        # so nothing from inside the error reaches a web page.
        log.warning("Mojang's version list couldn't be read: %s", exc)
        problem = (
            "Mojang's version list couldn't be read just now, so only the versions "
            "kept on this PC are offered. The app's log has the reason."
        )
    names = set(kept) | ({newest} if newest else set())
    found = [
        Version(
            minecraft=name,
            stable=True,
            released=None,
            java=False,
            kept=name in kept,
            latest=name == newest,
        )
        for name in names
    ]
    return sorted(found, key=lambda v: version_key(v.minecraft), reverse=True), problem


async def plan(minecraft: str) -> Plan:
    """What installing this version takes: a download of Mojang's newest,
    or the copy kept here."""
    from .versions import Download, Plan, VersionError

    if not VERSION_RE.match(minecraft):
        raise VersionError(f"'{minecraft}' isn't a Bedrock version.")
    kept = {entry["version"]: entry for entry in kept_versions()}
    if minecraft in kept:
        return Plan(
            type_id="bedrock",
            minecraft=minecraft,
            loader=None,
            downloads=[],
            jar="bedrock_server.exe",
            source="a copy this app downloaded earlier",
            verified=False,
            archive=str(kept_root() / f"bedrock-server-{minecraft}.zip"),
        )
    newest, url = await latest()
    if newest != minecraft:
        raise VersionError(
            f"Mojang only offers the newest Bedrock server ({newest}), and no copy of "
            f"{minecraft} was kept here, so it can't be installed."
        )
    spec = FileSpec(
        url=url,
        name=f"bedrock-server-{minecraft}.zip",
        allow_unverified=True,  # Mojang publishes no checksum for it
        max_bytes=MAX_ZIP_BYTES,
    )
    return Plan(
        type_id="bedrock",
        minecraft=minecraft,
        loader=None,
        downloads=[Download(spec)],
        jar="bedrock_server.exe",
        source="www.minecraft.net",
        verified=False,
        archive=str(kept_root() / spec.name),
    )


async def fetch(plan: Plan, job: JobHandle | None = None) -> dict[str, Any]:
    """The zip for this plan, downloaded and kept, or the kept one. Returns
    what to record about it, including its SHA-256 and whether an earlier
    download of the same version matched."""
    root = kept_root()
    root.mkdir(parents=True, exist_ok=True)
    archive = Path(plan.archive or "")
    if not plan.downloads:
        entry = _index(root).get(plan.minecraft) or {}
        if not archive.is_file():
            raise BedrockError(f"The kept copy of Bedrock {plan.minecraft} is no longer there.")
        sha256 = await asyncio.to_thread(_sha256, archive)
        if entry.get("sha256") and entry["sha256"] != sha256:
            raise BedrockError(
                f"The kept copy of Bedrock {plan.minecraft} has changed since it was "
                "downloaded, so it wasn't used."
            )
        return {
            "file": archive.name,
            "size": archive.stat().st_size,
            "sha256": sha256,
            "verified": False,
            "checked_with": None,
            "source": "kept copy",
            "kept": True,
            "earlier_sha256": entry.get("sha256"),
            "matches_earlier": True if entry.get("sha256") else None,
        }
    earlier = (_index(root).get(plan.minecraft) or {}).get("sha256")
    fetched = await downloads.download(
        plan.downloads[0].spec, root, job=job, label="Downloading the Bedrock server"
    )
    entry = {
        "sha256": fetched.sha256,
        "size": fetched.size,
        "downloaded_at": time.time(),
        "source": fetched.source,
    }
    _record_kept(root, plan.minecraft, entry)
    return {
        **fetched.to_dict(),
        "kept": False,
        "earlier_sha256": earlier,
        # None: nothing to compare with. False is reported in the install
        # log and the result: Mojang changed the file, or it was damaged.
        "matches_earlier": None if not earlier else earlier == fetched.sha256,
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


# ----------------------------------------------------------------------
# what the zip holds, and unpacking it
# ----------------------------------------------------------------------
def members(archive: Path) -> list[zipfile.ZipInfo]:
    """The zip's entries, each checked: no path leaves the folder, no
    links, and a sensible unpacked size."""
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
    total = 0
    for info in infos:
        try:
            check_archive_member(CHECK_BASE, info.filename)
        except PathSafetyError as exc:
            raise BedrockError(f"The Bedrock download wasn't used: {exc}") from None
        if zip_member_is_symlink(info):
            raise BedrockError("The Bedrock download holds a link, so it wasn't used.")
        total += info.file_size
    if total > MAX_UNPACKED_BYTES:
        raise BedrockError("The Bedrock download unpacks to far more than expected.")
    names = {info.filename.split("/", 1)[0] for info in infos}
    if "bedrock_server.exe" not in names and "bedrock_server" not in names:
        raise BedrockError("The download doesn't hold the Bedrock server program.")
    return infos


def shipped(infos: list[zipfile.ZipInfo]) -> dict[str, list[str]]:
    """What in the server folder belongs to Mojang's download: the top-level
    files and folders (except the ones that are the server's own), and each
    built-in pack folder."""
    top: set[str] = set()
    packs: set[str] = set()
    for info in infos:
        parts = info.filename.replace("\\", "/").strip("/").split("/")
        if not parts or not parts[0]:
            continue
        if parts[0] in PACK_FOLDERS:
            if len(parts) >= 2 and parts[1]:
                packs.add(f"{parts[0]}/{parts[1]}")
            continue
        if parts[0] not in KEEP:
            top.add(parts[0])
    return {"top": sorted(top), "packs": sorted(packs)}


def move_aside(directory: Path, keep: Path, record: dict[str, list[str]]) -> list[str]:
    """Move what the current download put in the folder into ``keep``,
    keeping its folder layout. Returns the relative paths moved."""
    moved = []
    for relative in [*record.get("top", []), *record.get("packs", [])]:
        source = directory / relative
        if not source.exists() or source.is_symlink():
            continue
        target = keep / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(relative)
    return moved


def unpack(archive: Path, directory: Path, infos: list[zipfile.ZipInfo]) -> list[str]:
    """Unpack the download into the server folder. A file the server keeps
    (worlds/, server.properties, allowlist.json, permissions.json) is only
    written when it isn't there yet, so a new server gets Mojang's defaults
    and an existing one keeps its own."""
    written = []
    with zipfile.ZipFile(archive) as zf:
        for info in infos:
            name = info.filename.replace("\\", "/")
            top = name.split("/", 1)[0]
            target = directory / name
            if top in KEEP and (directory / top).exists():
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            written.append(name)
    executable = directory / "bedrock_server"
    if executable.is_file() and os.name != "nt":
        executable.chmod(0o755)
    return written


async def install(
    ctx: ServerContext,
    plan: Plan,
    directory: Path,
    job: JobHandle | None = None,
    keep: Path | None = None,
) -> dict[str, Any]:
    """Fetch (or reuse) the zip and unpack it into ``directory``. With
    ``keep``, what the previous download put in the folder is moved there
    first (only once the new zip is here and checked), and listed under
    ``previous`` so the change can be rolled back. Returns what
    install_plan returns for the Java types."""
    require_terms(ctx.core.db)
    fetched = await fetch(plan, job=job)
    archive = kept_root() / fetched["file"]
    infos = await asyncio.to_thread(members, archive)
    moved: list[str] = []
    if keep is not None:
        old = shipped_record(ctx) or shipped(infos)
        keep.mkdir(parents=True, exist_ok=True)
        moved = await asyncio.to_thread(move_aside, directory, keep, old)
    if job:
        job.step("Unpacking the Bedrock server")
    try:
        await asyncio.to_thread(unpack, archive, directory, infos)
    except Exception:
        if keep is not None:
            # Put the old program back, so a failed update leaves the
            # server as it was.
            for relative in shipped(infos)["top"] + shipped(infos)["packs"]:
                path = directory / relative
                if relative not in moved and path.exists():
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            for relative in moved:
                target = directory / relative
                if target.exists():
                    shutil.rmtree(target) if target.is_dir() else target.unlink()
                shutil.move(str(keep / relative), str(target))
        raise
    record = shipped(infos)
    ctx.db.set_setting(SHIPPED_KEY, {**record, "version": plan.minecraft})
    log_path = _write_log(ctx, plan, fetched, directory)
    note = (
        "Mojang publishes no checksum for the Bedrock server, so it couldn't be checked "
        "against one. It was downloaded over a secure connection from minecraft.net, and its "
        f"SHA-256 ({fetched['sha256']}) is in the install log."
    )
    if fetched.get("matches_earlier") is False:
        note += (
            " It differs from the copy of the same version downloaded earlier "
            f"({fetched['earlier_sha256']})."
        )
    executable = "bedrock_server.exe" if (directory / "bedrock_server.exe").is_file() else ""
    executable = executable or (
        "bedrock_server" if (directory / "bedrock_server").is_file() else ""
    )
    if not executable:
        raise BedrockError("The Bedrock server program isn't there after unpacking.")
    return {
        "type": "bedrock",
        "minecraft_version": plan.minecraft,
        "loader_version": None,
        "jar": executable,
        "args_file": "",
        "files": [{**fetched, "role": "server"}],
        "verified": False,
        "unverified_note": note,
        "install_log": str(log_path),
        "source": plan.source,
        "sha256": fetched["sha256"],
        "matches_earlier": fetched.get("matches_earlier"),
        "moved_aside": moved,
    }


def _write_log(ctx: ServerContext, plan: Plan, fetched: dict[str, Any], directory: Path) -> Path:
    from .install import _log_path

    path = _log_path(ctx)
    lines = [
        f"Bedrock Dedicated Server {plan.minecraft}",
        f"into {directory}",
        f"from {fetched.get('source')}",
        f"file {fetched.get('file')} ({fetched.get('size')} bytes)",
        f"SHA-256 {fetched.get('sha256')}",
        "checksum: Mojang publishes none, so this download is unverified",
    ]
    if fetched.get("earlier_sha256"):
        same = "matches" if fetched.get("matches_earlier") else "DIFFERS FROM"
        lines.append(f"{same} the earlier download of this version ({fetched['earlier_sha256']})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def shipped_record(ctx: ServerContext) -> dict[str, list[str]] | None:
    value = ctx.db.get_setting(SHIPPED_KEY)
    return value if isinstance(value, dict) else None
