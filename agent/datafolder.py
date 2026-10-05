"""Moving the agent's data folder to the app-data folder, once.

Before the agent managed several servers, its data folder defaulted to
``<server folder>/mcsc-data``. The shared database and the agent's logs
cannot live inside one server's folder any more, so the default is now the
fixed app-data folder (``%ProgramData%\\Minecraft Server Controller`` on
Windows), the same place the installer will use.

On the first start of a version with this module, an existing
``<server>/mcsc-data`` is copied there:

1. Only when ``paths.data_dir`` is not set, ``<server>/mcsc-data`` holds a
   database, and the app-data folder holds none yet.
2. The target drive must have room for a full copy plus a margin.
3. Everything is copied into a staging folder inside the target first: the
   database through SQLite's backup API (a consistent copy, WAL included),
   every other file byte for byte, each one checked by SHA-256 against the
   original.
4. The database copy must pass ``PRAGMA integrity_check`` and have the same
   number of rows in every table as the original.
5. Paths stored in the copied database that point into the old folder
   (backup archives, crash evidence, archived mod jars) are pointed at the
   copies.
6. The staged files are moved into place, and ``layout.json`` and
   ``data-folder-move.json`` (what was copied and when) are written.
7. TLS paths in config.yaml that point into the old folder are pointed at
   the copied certificates, keeping comments, with the previous file saved
   as ``config.yaml.before-data-move``.

If any step fails, the staging folder is removed, the agent runs from the
old folder for this run, says why, and tries again on the next start. The
old folder is only ever read: nothing in it is changed, moved or deleted.

``python -m agent.datafolder`` prints the plan without changing anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("msc.datafolder")

STAGING = ".moving-in"
RECORD_FILE = "data-folder-move.json"
CONFIG_BACKUP_SUFFIX = ".before-data-move"
# Free space needed beyond the size of the copy itself.
SPACE_MARGIN_BYTES = 200 * 1024**2
SPACE_MARGIN_RATIO = 0.05

# Database columns that hold a path to a file the agent wrote.
PATH_COLUMNS = (
    ("backups", "path"),
    ("crashes", "report_path"),
    ("crashes", "log_path"),
    ("mod_versions", "archive_path"),
)
JSON_COLUMNS = (("crashes", "context"),)


class MoveError(RuntimeError):
    pass


@dataclass
class MovePlan:
    # not_needed: nothing to move. pending: will be copied on the next start.
    # done: already copied. blocked: cannot be copied (reason says why).
    status: str
    target: Path
    reason: str
    source: Path | None = None
    server_id: str | None = None
    files: int = 0
    bytes: int = 0
    free_bytes: int | None = None
    record: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target"] = str(self.target)
        data["source"] = str(self.source) if self.source else None
        return data


@dataclass
class MoveResult:
    ok: bool
    message: str
    source: Path | None = None
    target: Path | None = None
    files: int = 0
    bytes: int = 0
    tables: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = str(self.source) if self.source else None
        data["target"] = str(self.target) if self.target else None
        return data


# ----------------------------------------------------------------------
def _db_names(config) -> set[str]:
    name = config.paths.database
    return {name, f"{name}-wal", f"{name}-shm", f"{name}-journal"}


def _source_files(source: Path, skip: set[str]) -> list[Path]:
    files = []
    for root, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        for name in sorted(names):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            if path.parent == source and name in skip:
                continue
            files.append(path)
    return files


def _free_bytes(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def _read_record(target: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((target / RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def plan_move(config) -> MovePlan:
    """Work out what would happen. Reads only; changes nothing."""
    target = config.data_dir
    if config.data_dir_configured:
        return MovePlan(
            "not_needed",
            target,
            "The data folder is set in config.yaml (paths.data_dir), so it stays where it is.",
        )
    source = config.legacy_data_dir
    database = config.paths.database
    if (target / database).is_file():
        record = _read_record(target)
        if record:
            return MovePlan(
                "done",
                target,
                f"Copied from {record.get('moved_from')} on {record.get('moved_at')}.",
                source=Path(record["moved_from"]) if record.get("moved_from") else source,
                record=record,
            )
        return MovePlan("not_needed", target, "The data folder is already in use.")
    if source is None or not (source / database).is_file():
        return MovePlan("not_needed", target, "There is no old data folder to copy.")
    try:
        if source.resolve() == target.resolve():
            return MovePlan("not_needed", target, "The old and new data folders are the same.")
    except OSError:
        pass
    skip = _db_names(config)
    files = _source_files(source, skip)
    size = sum(p.stat().st_size for p in files)
    for name in skip:
        extra = source / name
        if extra.is_file():
            size += extra.stat().st_size
    free = _free_bytes(target)
    plan = MovePlan(
        "pending",
        target,
        "The old data folder will be copied to the new one on the next start.",
        source=source,
        server_id=config.default_server_id,
        files=len(files) + 1,  # + the database
        bytes=size,
        free_bytes=free,
    )
    needed = int(size * (1 + SPACE_MARGIN_RATIO)) + SPACE_MARGIN_BYTES
    if free is not None and free < needed:
        plan.status = "blocked"
        plan.reason = (
            f"Not enough free space on the drive for {target}: the copy needs about "
            f"{needed / 1024**3:.1f} GB and {free / 1024**3:.1f} GB is free. The agent keeps "
            f"using {source} until there is room, or until paths.data_dir is set in config.yaml."
        )
    return plan


# ----------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if _sha256(src) != _sha256(dst):
        raise MoveError(f"The copy of {src} does not match the original")
    return dst.stat().st_size


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def _copy_database(src: Path, dst: Path) -> dict[str, int]:
    source = sqlite3.connect(str(src))
    try:
        counts = _table_counts(source)
        dest = sqlite3.connect(str(dst))
        try:
            source.backup(dest)
            check = dest.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise MoveError(f"The database copy failed its integrity check: {check}")
            copied = _table_counts(dest)
        finally:
            dest.close()
    finally:
        source.close()
    if copied != counts:
        raise MoveError("The database copy does not have the same rows as the original")
    return counts


class _Remapper:
    """Points paths under the old folder at the same file under the new one."""

    def __init__(self, old: Path, new: Path):
        self.old = os.path.normcase(os.path.abspath(old))
        self.new = new

    def __call__(self, value: str) -> str | None:
        if not value:
            return None
        normal = os.path.normcase(os.path.abspath(value))
        if normal == self.old or not normal.startswith(self.old + os.sep):
            return None
        relative = os.path.abspath(value)[len(self.old) + 1 :]
        return str(self.new / relative)

    def walk(self, value: Any) -> tuple[Any, bool]:
        if isinstance(value, str):
            mapped = self(value)
            return (mapped, True) if mapped is not None else (value, False)
        if isinstance(value, list):
            changed = False
            out = []
            for item in value:
                new_item, item_changed = self.walk(item)
                out.append(new_item)
                changed = changed or item_changed
            return out, changed
        if isinstance(value, dict):
            changed = False
            out_dict = {}
            for key, item in value.items():
                new_item, item_changed = self.walk(item)
                out_dict[key] = new_item
                changed = changed or item_changed
            return out_dict, changed
        return value, False


def _rewrite_paths(db_path: Path, remap: _Remapper) -> int:
    changed = 0
    conn = sqlite3.connect(str(db_path))
    try:
        tables = set(_table_counts(conn))
        with conn:
            for table, column in PATH_COLUMNS:
                if table not in tables:
                    continue
                for row_id, value in conn.execute(
                    f"SELECT rowid, {column} FROM {table}"
                ).fetchall():
                    mapped = remap(value) if isinstance(value, str) else None
                    if mapped is not None:
                        conn.execute(
                            f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (mapped, row_id)
                        )
                        changed += 1
            for table, column in JSON_COLUMNS:
                if table not in tables:
                    continue
                for row_id, value in conn.execute(
                    f"SELECT rowid, {column} FROM {table}"
                ).fetchall():
                    if not isinstance(value, str) or not value:
                        continue
                    try:
                        data = json.loads(value)
                    except ValueError:
                        continue
                    new_data, was_changed = remap.walk(data)
                    if was_changed:
                        conn.execute(
                            f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                            (json.dumps(new_data), row_id),
                        )
                        changed += 1
    finally:
        conn.close()
    return changed


def _point_tls_at_copies(config, remap: _Remapper) -> list[str]:
    """Rewrite tls.* paths in config.yaml that point into the old folder."""
    from .config import set_yaml_value

    updates: dict[str, str] = {}
    for key in ("certificate", "private_key", "ca_certificate"):
        value = getattr(config.tls, key)
        if value and Path(value).expanduser().is_absolute():
            mapped = remap(str(Path(value).expanduser()))
            if mapped is not None:
                updates[f"tls.{key}"] = mapped
    if not updates:
        return []
    warnings: list[str] = []
    source = config.source
    if source and Path(source).is_file():
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        backup = path.with_name(path.name + CONFIG_BACKUP_SUFFIX)
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        for dotted, value in updates.items():
            text, changed = set_yaml_value(text, dotted, value)
            if not changed:
                warnings.append(
                    f"{dotted} could not be updated in {path}; it still points at the old folder."
                )
        path.write_text(text, encoding="utf-8")
    for dotted, value in updates.items():
        config.set(dotted, value)
    return warnings


def run_move(config, plan: MovePlan) -> MoveResult:
    """Copy, verify, then switch. The old folder is only read."""
    if plan.status != "pending" or plan.source is None:
        raise MoveError(f"Nothing to copy: {plan.reason}")
    source, target = plan.source, plan.target
    from .security.certs import secure_directory

    created = not target.exists()
    secure_directory(target)
    staging = target / STAGING
    if staging.exists():
        shutil.rmtree(staging)  # a previous attempt's partial copy: ours to remove
    staging.mkdir(parents=True)
    result = MoveResult(False, "", source=source, target=target)
    try:
        database = config.paths.database
        result.tables = _copy_database(source / database, staging / database)
        copied = 1
        size = (staging / database).stat().st_size
        for path in _source_files(source, _db_names(config)):
            relative = path.relative_to(source)
            size += _copy_verified(path, staging / relative)
            copied += 1
        _rewrite_paths(staging / database, _Remapper(source, target))
        # Switch: move each staged entry into the target folder.
        for entry in sorted(staging.iterdir()):
            destination = target / entry.name
            if destination.exists():
                raise MoveError(f"{destination} already exists, so nothing was replaced")
            os.replace(entry, destination)
        staging.rmdir()
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if created:
            shutil.rmtree(target, ignore_errors=True)
        result.message = f"The data folder could not be copied: {exc}"
        return result
    result.files, result.bytes = copied, size
    record = {
        "moved_from": str(source),
        "moved_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": copied,
        "bytes": size,
        "database_rows": result.tables,
        "note": "The old folder was left in place and was not changed.",
    }
    (target / RECORD_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    from .config import LAYOUT_FILE, LAYOUT_VERSION

    (target / LAYOUT_FILE).write_text(
        json.dumps({"layout": LAYOUT_VERSION, "flat_server": plan.server_id}, indent=2),
        encoding="utf-8",
    )
    try:
        result.warnings += _point_tls_at_copies(config, _Remapper(source, target))
    except OSError as exc:
        result.warnings.append(
            f"config.yaml could not be updated ({exc}); its certificate paths still point "
            "at the old folder, which is still there."
        )
    result.ok = True
    result.message = (
        f"Agent data copied from {source} to {target} and checked "
        f"({copied} files, {size / 1024**2:.0f} MB). The old folder was left in place."
    )
    return result


def apply_at_startup(config) -> MoveResult | None:
    """Copy the old data folder if that is due. On failure, keep using the
    old folder for this run. Returns None when there was nothing to do."""
    plan = plan_move(config)
    if plan.status == "blocked" and plan.source is not None:
        config.use_data_dir_for_this_run(plan.source)
        return MoveResult(False, plan.reason, source=plan.source, target=plan.target)
    if plan.status != "pending":
        return None
    result = run_move(config, plan)
    if not result.ok and plan.source is not None:
        result.message += (
            f" The agent is using {plan.source} for now and will try again next start."
        )
        config.use_data_dir_for_this_run(plan.source)
    return result


# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from .config import Config

    parser = argparse.ArgumentParser(
        description="Show where the agent keeps its data and whether it will be moved. "
        "Changes nothing."
    )
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--env", help="Path to the .env file")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args(argv)
    config = Config.load(args.config, args.env)
    plan = plan_move(config)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
        return 0
    print(f"Data folder:  {plan.target}")
    print(f"Status:       {plan.status}")
    print(f"              {plan.reason}")
    if plan.status in ("pending", "blocked"):
        print(f"Copy from:    {plan.source}")
        print(f"Files:        {plan.files}")
        print(f"Size:         {plan.bytes / 1024**2:.0f} MB")
        free = f"{plan.free_bytes / 1024**3:.1f} GB" if plan.free_bytes is not None else "Unknown"
        print(f"Free space:   {free}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
