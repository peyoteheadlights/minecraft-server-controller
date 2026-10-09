"""The old ``setup.ps1`` copy, after the installer moved its settings over.

When the installer moves a ``setup.ps1`` copy over, it copies the settings
(every file checked) and leaves the old folder exactly as it was, writing
``old-copy.json`` in the data folder: where the old copy is, its version and
when it was moved. A few days later (``OFFER_AFTER_DAYS``), once the new
copy has been running, App settings shows "Your old copy at C:\\… is no
longer used. Remove it?".

Removing it is careful, because that folder is a folder of the person's own:

* It is refused when the folder is a git checkout (it has ``.git``): that is
  someone's working copy of the code, not just an install.
* It is refused when it holds, or is inside, a Minecraft server folder or
  this app's data folder.
* Only the app's own files are removed, by name (``KNOWN``). Anything else
  in there (backups, logs, worlds, files the person put there) is kept and
  listed, and the folder itself is removed only when nothing else is left.
* The program that is running now must not be the old copy.

Deleting files is not running a program, so this stays within house rule 2.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from . import appinfo

RECORD = "old-copy.json"
OFFER_AFTER_DAYS = 7
DAY = 86400.0

# The files and folders a setup.ps1 copy is made of. Nothing else is removed.
KNOWN = (
    "agent",
    "installer",
    "scripts",
    "tests",
    "docs",
    "packaging",
    "config",
    ".venv",
    ".github",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "certs",
    ".env",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "setup.ps1",
    "setup.cmd",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "requirements.lock",
    "requirements-dev.txt",
    "requirements-dev.lock",
    "requirements-build.txt",
    "requirements-build.lock",
)


class OldCopyError(RuntimeError):
    pass


def _record_path(config) -> Path:
    return Path(config.data_dir) / RECORD


def read(config) -> dict[str, Any] | None:
    try:
        data = json.loads(_record_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("path") or data.get("removed_at"):
        return None
    return data


def _moved_at(data: dict[str, Any]) -> float | None:
    import datetime as dt

    try:
        return dt.datetime.fromisoformat(str(data.get("moved_at"))).timestamp()
    except ValueError:
        return None


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def problems(folder: Path, config) -> list[str]:
    """Why this folder can't be removed, if anything stops it."""
    found = []
    if (folder / ".git").exists():
        found.append(
            "It's a git checkout (it has a .git folder), so it may be someone's working copy of "
            "the code. Delete it yourself if you don't need it."
        )
    if _inside(appinfo.program_dir(), folder):
        found.append("The app is running from that folder now.")
    data = Path(config.data_dir)
    if _inside(data, folder):
        found.append(f"This app's data folder ({data}) is inside it.")
    for server_id in config.server_ids:
        server = config.for_server(server_id)
        server_dir = Path(server.server_dir)
        if _inside(server_dir, folder) or _inside(folder, server_dir):
            found.append(f"The Minecraft server folder {server_dir} is inside it, or holds it.")
        if _inside(server.backup_dir, folder):
            found.append(f"Backups are kept in it ({server.backup_dir}).")
    for used in (config.tls_certificate, config.tls_private_key, config.tls_ca_certificate):
        if used is not None and _inside(used, folder):
            found.append(f"The dashboard's certificate is still read from it ({used}).")
            break
    return found


def status(config, now: float | None = None) -> dict[str, Any] | None:
    """What App settings shows, or None when there's nothing to offer."""
    data = read(config)
    if data is None or not appinfo.installed():
        return None
    folder = Path(str(data["path"]))
    if not folder.exists():
        return None
    moved = _moved_at(data)
    now = time.time() if now is None else now
    return {
        "path": str(folder),
        "version": data.get("version"),
        "moved_at": data.get("moved_at"),
        "offer": moved is not None and now - moved >= OFFER_AFTER_DAYS * DAY,
        "problems": problems(folder, config),
        "removes": sorted(name for name in KNOWN if (folder / name).exists()),
    }


def remove(config) -> dict[str, Any]:
    """Remove the app's own files from the old copy. Keeps everything else."""
    data = read(config)
    if data is None:
        raise OldCopyError("There's no old copy to remove.")
    if not appinfo.installed():
        raise OldCopyError("Only an installed copy removes the old one.")
    folder = Path(str(data["path"]))
    stopped = problems(folder, config)
    if stopped:
        raise OldCopyError(stopped[0])
    removed, failed = [], []
    for name in KNOWN:
        path = folder / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(name)
        except OSError as exc:
            failed.append(f"{name}: {exc.strerror or exc}")
    kept = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    if folder.is_dir() and not kept:
        try:
            folder.rmdir()
        except OSError:
            pass
    if not failed:
        data["removed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        data["kept"] = kept
        _record_path(config).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {
        "ok": not failed,
        "path": str(folder),
        "removed": removed,
        "kept": kept,
        "failed": failed,
        "folder_removed": not folder.exists(),
    }
