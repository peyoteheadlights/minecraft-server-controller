"""Restore points: what an install or update can roll back to by itself.

Before anything changes, the current settings (``config.yaml``, ``.env``),
the database and the program version are saved under
``<data folder>/restore-points/<when>-<version>/``, with a SHA-256 for every
file. The previous program folder is kept next to the new one
(``<program folder>.previous``) until the update has been checked, so a
failed update puts both back. The last few restore points are kept.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.config import DEFAULTS, default_data_root

from . import layout
from .fileops import Report, copy_database, copy_files, sha256_file

MANIFEST = "restore-point.json"


class RestoreError(RuntimeError):
    pass


def database_path(config_path: Path) -> Path | None:
    """The database a config.yaml uses, read from the file itself (nothing
    is loaded into this process's environment)."""
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    paths = data.get("paths") if isinstance(data, dict) else None
    paths = paths if isinstance(paths, dict) else {}
    data_dir = str(paths.get("data_dir") or "").strip()
    root = Path(data_dir).expanduser() if data_dir else default_data_root()
    name = str(paths.get("database") or DEFAULTS["paths"]["database"])
    db = Path(name).expanduser()
    return db if db.is_absolute() else root / db


@dataclass
class RestorePoint:
    folder: Path
    manifest: dict[str, Any]

    @property
    def version(self) -> str | None:
        return self.manifest.get("version")

    def to_dict(self) -> dict[str, Any]:
        return {"folder": str(self.folder), **self.manifest}


def create(
    root: Path,
    *,
    version: str | None,
    config_path: Path,
    env_path: Path,
    program_dir: Path | None,
    reason: str,
    report: Report | None = None,
) -> RestorePoint:
    """Save the settings, secrets and database. Raises on any failure, so an
    update never starts without a complete restore point."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = layout.restore_points_dir(root) / f"{stamp}-{version or 'unknown'}"
    n = 1
    while folder.exists():
        folder = folder.with_name(f"{stamp}-{version or 'unknown'}-{n}")
        n += 1
    folder.mkdir(parents=True)
    files: dict[str, dict[str, str]] = {}
    pairs = []
    for name, source in (("config.yaml", config_path), (".env", env_path)):
        if source.is_file():
            pairs.append((source, folder / name))
            files[name] = {"original": str(source)}
    copied = copy_files(pairs, report)
    for name in files:
        files[name]["sha256"] = copied.hashes[str(folder / name)]
    db = database_path(config_path) if config_path.is_file() else None
    if db is not None and db.is_file():
        copy_database(db, folder / "database.sqlite3")
        files["database.sqlite3"] = {
            "original": str(db),
            "sha256": sha256_file(folder / "database.sqlite3"),
            "kind": "sqlite",
        }
    manifest = {
        "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "version": version,
        "reason": reason,
        "program_dir": str(program_dir) if program_dir else None,
        "files": files,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prune(root)
    return RestorePoint(folder, manifest)


def load(folder: Path) -> RestorePoint:
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RestoreError(f"The restore point in {folder} can't be read: {exc}") from exc
    return RestorePoint(folder, manifest)


def restore(point: RestorePoint) -> list[str]:
    """Put every saved file back where it came from, checking each one.
    Returns what was put back."""
    restored = []
    for name, info in point.manifest.get("files", {}).items():
        saved = point.folder / name
        if sha256_file(saved) != info["sha256"]:
            raise RestoreError(f"The saved copy of {name} has changed, so it wasn't used.")
        target = Path(info["original"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if info.get("kind") == "sqlite":
            for extra in ("-wal", "-shm"):
                Path(str(target) + extra).unlink(missing_ok=True)
        temp = target.with_name(target.name + ".restoring")
        shutil.copyfile(saved, temp)
        temp.replace(target)
        restored.append(str(target))
    return restored


def prune(root: Path, keep: int = layout.KEEP_RESTORE_POINTS) -> None:
    folder = layout.restore_points_dir(root)
    points = sorted(p for p in folder.iterdir() if (p / MANIFEST).is_file())
    for old in points[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def latest(root: Path) -> RestorePoint | None:
    folder = layout.restore_points_dir(root)
    if not folder.is_dir():
        return None
    points = sorted(p for p in folder.iterdir() if (p / MANIFEST).is_file())
    return load(points[-1]) if points else None
