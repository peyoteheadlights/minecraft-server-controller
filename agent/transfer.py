"""Move to a new PC: everything this app knows in one file, and putting it
back on the other PC.

Export ("Export everything" in App settings) writes one ``.zip``:

  manifest.json        what is inside, and where each server's folder was
  config.yaml          the settings (no passwords or keys are kept there)
  data.json            schedules, players seen, mod sources, preferences,
                       and helper accounts by name and role only
  servers/<id>/...     each server's folder: mods, configs, server.properties
                       worlds only when ticked; logs and crash reports never
  backups/<id>/...     the backup files, only when ticked
  secrets.bin          only when ticked: .env's values, helpers' password
                       hashes, phone subscriptions, and server.properties'
                       RCON and management passwords, encrypted with a
                       passphrase (scrypt, then AES-256-GCM)

Without "include secrets" nothing that lets someone into the dashboard, the
PC or the servers is in the file: on the new PC the owner sets a password
again in setup, and helpers get new passwords.

Import is for the installer (``python -m installer.import_from_pc``): it
puts each server folder under a folder chosen on the new PC, points the
settings at the new places, and loads the rest into the new database.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import __version__
from .config import SECRET_ENV_KEYS
from .minecraft.properties import FILENAME, PropertiesFile, world_folders
from .security.paths import check_archive_member, directory_size, zip_member_is_symlink

FORMAT = 1
FOLDER = "exports"
TOKEN_RE_TEXT = r"^[0-9a-f]{32}$"
KEEP_SECONDS = 24 * 3600
# Never copied from a server folder: they belong to the old PC or are noise.
SKIP_FOLDERS = {"logs", "crash-reports", "debug", ".fabric", "cache"}
SKIP_FILES = {"session.lock"}
# server.properties values that are passwords.
SECRET_PROPERTIES = ("rcon.password", "management-server-secret")
# Database tables carried over, with the columns that identify a row.
DATA_TABLES = ("servers", "players", "schedules", "settings", "mod_versions", "mod_history")
ACCOUNT_COLUMNS = ("username", "role", "servers", "created_at", "created_by")
MAGIC = b"MCSC-SECRETS-1"
AAD = b"minecraft-server-control export secrets"
MIN_PASSPHRASE = 10


class TransferError(RuntimeError):
    pass


# ----------------------------------------------------------------------
# the secrets part: scrypt + AES-GCM
# ----------------------------------------------------------------------
def _key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def encrypt(data: dict[str, Any], passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(passphrase) < MIN_PASSPHRASE:
        raise TransferError(f"The passphrase needs at least {MIN_PASSPHRASE} characters.")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    sealed = AESGCM(_key(passphrase, salt)).encrypt(nonce, json.dumps(data).encode("utf-8"), AAD)
    return MAGIC + salt + nonce + sealed


def decrypt(blob: bytes, passphrase: str) -> dict[str, Any]:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC):
        raise TransferError("The secrets in this file aren't in a form this app knows.")
    body = blob[len(MAGIC) :]
    salt, nonce, sealed = body[:16], body[16:28], body[28:]
    try:
        plain = AESGCM(_key(passphrase, salt)).decrypt(nonce, sealed, AAD)
    except InvalidTag as exc:
        raise TransferError("That passphrase isn't the one the file was saved with.") from exc
    loaded = json.loads(plain)
    if not isinstance(loaded, dict):
        raise TransferError("The secrets in this file can't be read.")
    return loaded


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------
@dataclass
class Options:
    worlds: bool = False
    backups: bool = False
    secrets: bool = False
    passphrase: str = ""


def _server_files(directory: Path, worlds: bool) -> list[tuple[Path, str]]:
    """Every file of a server folder to copy, with its path inside it."""
    skip_worlds = set() if worlds else world_folders(directory)
    out: list[tuple[Path, str]] = []
    for root, dirs, names in os.walk(directory, followlinks=False):
        here = Path(root)
        top = here == directory
        dirs[:] = sorted(
            d
            for d in dirs
            if not os.path.islink(os.path.join(root, d))
            and ".replaced-" not in d
            and not (top and (d in SKIP_FOLDERS or d in skip_worlds))
        )
        for name in sorted(names):
            full = here / name
            if name in SKIP_FILES or full.is_symlink():
                continue
            out.append((full, full.relative_to(directory).as_posix()))
    return out


def _backups(config, db, server_id: str) -> list[tuple[dict[str, Any], Path]]:
    folder = config.for_server(server_id).backup_dir
    out = []
    for row in db.query("SELECT * FROM backups WHERE server_id = ? ORDER BY id", (server_id,)):
        path = Path(row["path"])
        if path.parent == folder and path.is_file() and not path.is_symlink():
            out.append((row, path))
    return out


def _config_yaml(config) -> str:
    data = copy.deepcopy(config._data)
    servers = data.pop("servers")
    return yaml.safe_dump({"servers": servers, **data}, sort_keys=False, allow_unicode=True, width=10**6)


def _properties_without_secrets(path: Path) -> tuple[bytes, dict[str, str]]:
    """server.properties with its passwords blanked, and those passwords."""
    text = path.read_text(encoding="utf-8", errors="replace")
    found: dict[str, str] = {}
    lines = []
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in SECRET_PROPERTIES:
            if value.strip():
                found[key.strip()] = value.strip()
            line = f"{key}="
        lines.append(line)
    return ("\n".join(lines) + "\n").encode("utf-8"), found


def estimate(core) -> dict[str, Any]:
    """Sizes shown before exporting, measured from disk."""
    servers = []
    for ctx in core.servers.values():
        base = ctx.config.server_dir
        world = sum(directory_size(base / name) for name in world_folders(base))
        files = sum(f.stat().st_size for f, _ in _server_files(base, worlds=False) if f.exists())
        backups = sum(p.stat().st_size for _, p in _backups(core.config, core.db, ctx.server_id))
        servers.append(
            {"id": ctx.server_id, "name": ctx.name, "files": files, "worlds": world, "backups": backups}
        )
    return {"servers": servers}


def export(core, target: Path, options: Options, progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Write the export file. Returns the manifest."""
    if options.secrets and len(options.passphrase) < MIN_PASSPHRASE:
        raise TransferError(f"The passphrase needs at least {MIN_PASSPHRASE} characters.")
    config, db = core.config, core.db
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "app_version": __version__,
        "made_at": time.time(),
        "includes": {"worlds": options.worlds, "backups": options.backups, "secrets": options.secrets},
        "servers": [],
    }
    hidden: dict[str, Any] = {"env": {}, "account_hashes": {}, "push_subscriptions": [], "properties": {}}
    data: dict[str, Any] = {}
    for table in DATA_TABLES:
        data[table] = db.query(f"SELECT * FROM {table}")  # noqa: S608 - fixed names
    data["accounts"] = db.query(f"SELECT {', '.join(ACCOUNT_COLUMNS)} FROM accounts")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr("config.yaml", _config_yaml(config))
        for server_id in config.server_ids:
            view = config.for_server(server_id)
            base = view.server_dir
            entry = {
                "id": server_id,
                "name": view.server.name or server_id,
                "type": view.server.type,
                "directory": str(base),
                "folder_name": base.name,
                "backups": [],
            }
            for full, relative in _server_files(base, options.worlds):
                name = f"servers/{server_id}/{relative}"
                try:
                    if relative == FILENAME:
                        clean, found = _properties_without_secrets(full)
                        if found:
                            hidden["properties"][server_id] = found
                        zf.writestr(name, clean)
                    else:
                        zf.write(full, name)
                except OSError as exc:
                    raise TransferError(f"{full} couldn't be read: {exc.strerror or exc}") from exc
                if progress:
                    progress(1)
            if options.backups:
                for row, path in _backups(config, db, server_id):
                    zf.write(path, f"backups/{server_id}/{path.name}", compress_type=zipfile.ZIP_STORED)
                    kept = {k: v for k, v in row.items() if not k.startswith("copy_") and k != "id"}
                    entry["backups"].append(kept)
                    if progress:
                        progress(1)
            manifest["servers"].append(entry)
        if options.secrets:
            env_values = {k: os.environ[k] for k in SECRET_ENV_KEYS if os.environ.get(k)}
            env_values["MCSC_ADMIN_USERNAME"] = config.admin_username
            hidden["env"] = env_values
            hidden["account_hashes"] = {
                r["username"]: r["password_hash"]
                for r in db.query("SELECT username, password_hash FROM accounts")
            }
            hidden["push_subscriptions"] = db.query("SELECT * FROM push_subscriptions")
            zf.writestr("secrets.bin", encrypt(hidden, options.passphrase))
        zf.writestr("data.json", json.dumps(data, indent=1, default=str))
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return manifest


def count_items(core, options: Options) -> int:
    total = 0
    for ctx in core.servers.values():
        total += len(_server_files(ctx.config.server_dir, options.worlds))
        if options.backups:
            total += len(_backups(core.config, core.db, ctx.server_id))
    return total


def folder(config) -> Path:
    path = Path(config.data_dir) / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in path.iterdir():
        try:
            if now - old.stat().st_mtime > KEEP_SECONDS:
                old.unlink()
        except OSError:
            pass
    return path


# ----------------------------------------------------------------------
# import (run by the installer on the new PC)
# ----------------------------------------------------------------------
def read_manifest(path: Path) -> dict[str, Any]:
    """Open an export file and check it before anything is written."""
    try:
        with zipfile.ZipFile(path) as zf:
            check_base = Path(path).parent / "import-check"
            for info in zf.infolist():
                check_archive_member(check_base, info.filename, zip_member_is_symlink(info))
            manifest = json.loads(zf.read("manifest.json"))
    except KeyError as exc:
        raise TransferError("This isn't a file made by Export everything.") from exc
    except zipfile.BadZipFile as exc:
        raise TransferError(f"This file can't be opened: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise TransferError("This file was made by a version of this app that this one can't read.")
    return manifest


def _folder_name(entry: dict[str, Any]) -> str:
    raw = str(entry.get("folder_name") or entry["id"])
    cleaned = "".join(c for c in raw if c.isalnum() or c in " ._-()").strip(" .")
    return cleaned or str(entry["id"])


def plan_import(manifest: dict[str, Any], servers_root: Path) -> list[dict[str, Any]]:
    """Where each server's folder will go on this PC. Refuses folders that
    already have files in them."""
    out = []
    for entry in manifest["servers"]:
        target = Path(servers_root) / _folder_name(entry)
        if target.exists() and any(target.iterdir()):
            raise TransferError(f"{target} already has files in it. Choose another folder.")
        out.append({"id": entry["id"], "name": entry.get("name"), "from": entry["directory"], "to": str(target)})
    return out


def _extract_prefix(zf: zipfile.ZipFile, prefix: str, target: Path) -> int:
    written = 0
    for info in zf.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        relative = info.filename[len(prefix) :]
        destination = check_archive_member(target, relative, zip_member_is_symlink(info))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(destination, "wb") as out:
            while chunk := src.read(1024 * 1024):
                out.write(chunk)
        written += 1
    return written


def _new_config(text: str, places: dict[str, str]) -> str:
    loaded = yaml.safe_load(text) or {}
    servers = loaded.get("servers") or ([loaded.pop("server")] if loaded.get("server") else [])
    for server in servers:
        if server.get("id") in places:
            server["directory"] = places[server["id"]]
    loaded["servers"] = servers
    loaded.pop("server", None)
    # Folders that belonged to the old PC: this PC's own defaults are used.
    loaded.setdefault("paths", {})["data_dir"] = ""
    if isinstance(loaded.get("backups"), dict):
        loaded["backups"]["offsite_directory"] = ""
    for server in servers:
        if isinstance(server.get("backups"), dict):
            server["backups"].pop("offsite_directory", None)
    return yaml.safe_dump(loaded, sort_keys=False, allow_unicode=True, width=10**6)


def _insert(db, table: str, row: dict[str, Any], drop: tuple[str, ...] = ("id",)) -> None:
    columns = {r["name"] for r in db.query(f"PRAGMA table_info({table})")}
    keep = {k: v for k, v in row.items() if k in columns and k not in drop}
    if not keep:
        return
    names = ", ".join(keep)
    marks = ", ".join("?" for _ in keep)
    db.execute(f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})", tuple(keep.values()))  # noqa: S608


def import_all(
    path: Path,
    servers_root: Path,
    config_path: Path,
    env_path: Path,
    passphrase: str | None = None,
    write_env: Callable[[Path, str, str], None] | None = None,
) -> dict[str, Any]:
    """Put an export in place on this PC. Returns what was done."""
    from .config import Config
    from .database.db import Database

    manifest = read_manifest(path)
    places = plan_import(manifest, servers_root)
    hidden: dict[str, Any] | None = None
    with zipfile.ZipFile(path) as zf:
        if manifest["includes"].get("secrets"):
            if passphrase is not None:
                hidden = decrypt(zf.read("secrets.bin"), passphrase)
        moved = {p["id"]: p["to"] for p in places}
        files = 0
        for place in places:
            files += _extract_prefix(zf, f"servers/{place['id']}/", Path(place["to"]))
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.is_file():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            config_path.replace(config_path.with_name(f"{config_path.name}.before-import-{stamp}"))
        config_path.write_text(_new_config(zf.read("config.yaml").decode("utf-8"), moved), encoding="utf-8")
        config = Config.load(config_path, env_path)
        db = Database(config.database_path)
        data = json.loads(zf.read("data.json"))
        for table in DATA_TABLES:
            for row in data.get(table, []):
                if table == "servers" and row.get("id") in moved:
                    row = {**row, "directory": moved[row["id"]]}
                _insert(db, table, row, drop=() if table in ("servers", "settings", "players") else ("id",))
        backups = 0
        for entry in manifest["servers"]:
            if entry["id"] not in moved:
                continue
            folder = config.for_server(entry["id"]).backup_dir
            for row in entry.get("backups", []):
                name = PurePosixPath(str(row.get("name") or "")).name
                if not name:
                    continue
                member = f"backups/{entry['id']}/{name}"
                if member not in zf.namelist():
                    continue
                destination = check_archive_member(folder, name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(destination, "wb") as out:
                    while chunk := src.read(1024 * 1024):
                        out.write(chunk)
                _insert(db, "backups", {**row, "path": str(destination)})
                backups += 1
        helpers = 0
        hashes = (hidden or {}).get("account_hashes", {})
        for row in data.get("accounts", []):
            password_hash = hashes.get(row.get("username"))
            if not password_hash:
                continue  # without secrets, helpers are added again with new passwords
            _insert(db, "accounts", {**row, "password_hash": password_hash}, drop=())
            helpers += 1
        if hidden:
            for sub in hidden.get("push_subscriptions", []):
                _insert(db, "push_subscriptions", sub, drop=())
            for server_id, values in hidden.get("properties", {}).items():
                if server_id in moved:
                    props = Path(moved[server_id]) / FILENAME
                    if props.is_file():
                        current = PropertiesFile.read(props)
                        for key, value in values.items():
                            current.set(key, value)
                        current.write(props)
            if write_env:
                for key, value in hidden.get("env", {}).items():
                    write_env(Path(env_path), key, value)
        db.audit("import_from_pc", user="installer", detail=f"{len(places)} servers")
    return {"servers": places, "files": files, "backups": backups, "helpers": helpers, "secrets": bool(hidden)}
