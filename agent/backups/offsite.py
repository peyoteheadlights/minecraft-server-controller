"""A second copy of each backup, off the PC.

The folder is another drive (a USB disk) or a folder a cloud app keeps in
sync (OneDrive, Google Drive, Dropbox), chosen with the folder picker. Rules:

  * the local backup always comes first and is never skipped or undone
    because the second copy failed; a missing drive is a warning
  * a backup is copied only after it has verified, to a ``.part`` file that
    is renamed into place only once its SHA-256 matches the backup's own
  * the copies follow the same retention: when a backup is removed, so is
    its copy (and only files this app wrote, inside its own subfolder)
  * each copy's status is recorded and shown as it is: "Copied and checked",
    or the reason it failed ("drive not connected")

Copies go to ``<folder>/Minecraft Server Control/<server id>/<backup name>``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..security.paths import PathSafetyError, _system_folders, assert_not_symlink, is_inside

if TYPE_CHECKING:
    from ..jobs import JobHandle

log = logging.getLogger("msc.backups.offsite")

SUBFOLDER = "Minecraft Server Control"
OK = "ok"
FAILED = "failed"
CHUNK = 4 * 1024 * 1024


class OffsiteError(RuntimeError):
    pass


def check_folder(value: str, protected: list[Path]) -> Path:
    """Validate the folder chosen for second copies. It must already exist
    (a drive that is plugged in, a cloud folder that is set up), be a real
    folder, not be a system folder, and not overlap the server folders or
    this app's own data, where a copy would be no safer than the original."""
    raw = (value or "").strip()
    if not raw or "\0" in raw:
        raise PathSafetyError("Choose a folder for the second copies.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PathSafetyError("Choose the whole path to a folder, for example E:\\Backups")
    if not path.exists():
        raise PathSafetyError(
            f"{path} isn't there. If it's on a USB drive, plug the drive in first."
        )
    assert_not_symlink(path)
    if not path.is_dir():
        raise PathSafetyError(f"{path} is a file, not a folder.")
    resolved = path.resolve()
    for system in _system_folders():
        if is_inside(system, resolved):
            raise PathSafetyError(f"{path} is inside a system folder ({system}).")
    for folder in protected:
        folder = Path(folder)
        if is_inside(folder, resolved) or is_inside(resolved, folder):
            raise PathSafetyError(
                f"{path} overlaps {folder}. A second copy has to be somewhere else, or it "
                "is lost along with the first."
            )
    probe = resolved / f".mcsc-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise PathSafetyError(f"This app can't write to {path}: {exc}") from exc
    return resolved


def target_folder(root: Path, server_id: str) -> Path:
    return Path(root) / SUBFOLDER / server_id


def unavailable_reason(root: Path) -> str | None:
    """Why the folder can't be used right now, in plain words, or None."""
    root = Path(root)
    anchor = Path(root.anchor) if root.anchor else None
    if anchor is not None and not anchor.exists():
        return "drive not connected"
    if not root.exists():
        return "folder not found"
    if not root.is_dir():
        return "not a folder"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(
    source: Path, destination: Path, expected_sha256: str, job: JobHandle | None = None
) -> None:
    """Copy to a .part file, check its hash against the backup's, then rename
    it into place. Raises OffsiteError with a plain reason."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    size = source.stat().st_size
    if job:
        job.step("Copying the backup off the PC", total=size, unit="bytes")
    free = shutil.disk_usage(destination.parent).free
    if free < size + 50 * 1024**2:
        raise OffsiteError(
            f"not enough space there ({free / 1024**3:.1f} GB free, the backup is "
            f"{size / 1024**3:.1f} GB)"
        )
    digest = hashlib.sha256()
    try:
        with open(source, "rb") as src, open(part, "wb") as out:
            while chunk := src.read(CHUNK):
                out.write(chunk)
                digest.update(chunk)
                if job:
                    job.advance(len(chunk))
            out.flush()
            os.fsync(out.fileno())
        if digest.hexdigest() != expected_sha256:
            raise OffsiteError("the backup changed while it was being copied")
        if job:
            job.step("Checking the copy")
        # Read back from the other drive: what was written is what counts.
        if _sha256(part) != expected_sha256:
            raise OffsiteError("the copy didn't match the backup when read back")
        os.replace(part, destination)
    except OffsiteError:
        part.unlink(missing_ok=True)
        raise
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise OffsiteError(_plain(exc, destination)) from exc


def _plain(exc: OSError, destination: Path) -> str:
    reason = unavailable_reason(destination.parent.parent.parent)
    if reason:
        return reason
    if getattr(exc, "winerror", None) in (21, 1167) or exc.errno in (19,):  # not ready, gone
        return "drive not connected"
    if exc.errno == 28:
        return "the drive is full"
    if exc.errno == 13:
        return "this app isn't allowed to write there"
    return f"the copy couldn't be written ({exc.strerror or exc})"


def copy_status(row: dict[str, Any], root: Path | None) -> dict[str, Any]:
    """How a backup's second copy stands now: what was recorded, checked
    against what is actually on the drive (a copy someone deleted, or a
    drive that was unplugged, is not reported as there)."""
    status = row.get("copy_status")
    path = row.get("copy_path")
    if not status:
        return {"state": "none"}
    if status == FAILED:
        return {"state": "failed", "reason": row.get("copy_detail") or "unknown reason"}
    if path:
        copy = Path(path)
        reason = unavailable_reason(copy.parent.parent.parent)
        if reason:
            return {"state": "unreachable", "reason": reason, "path": path}
        if not copy.is_file():
            return {"state": "missing", "reason": "the copy isn't there any more", "path": path}
    return {
        "state": "ok",
        "path": path,
        "checked_at": row.get("copy_checked_at"),
        "in_folder": bool(root and path and is_inside(Path(root), Path(path))),
    }


def remove_copy(row: dict[str, Any], root: Path | None) -> bool:
    """Delete a backup's second copy, if it is one this app wrote: inside the
    chosen folder's own subfolder, with the backup's name."""
    path = row.get("copy_path")
    if not path or not root:
        return False
    copy = Path(path)
    if copy.name != row.get("name") or not is_inside(Path(root) / SUBFOLDER, copy):
        return False
    try:
        copy.unlink(missing_ok=True)
        return True
    except OSError:
        log.warning("could not remove the off-PC copy %s", copy, exc_info=True)
        return False


def record(db, backup_id: int, status: str, path: str | None, detail: str | None) -> None:
    db.execute(
        "UPDATE backups SET copy_status = ?, copy_path = ?, copy_detail = ?, copy_checked_at = ? "
        "WHERE id = ?",
        (status, path, (detail or "")[:400] or None, time.time(), backup_id),
    )
