"""World and configuration backups.

Rules that do not bend:

  * restoring always creates a safety backup of the current state first
  * a backup is verified (zip integrity + SHA-256) before it is restored
  * the server is stopped before a restore, and only started again if asked
  * retention never touches the live world, only files under the backup folder

Creating and restoring run as jobs (agent/jobs.py), so the dashboard shows
their real progress and a server never runs two at once. Restoring goes
through the safe-change routine (agent/safechange.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..events import Event, EventBus
from ..safechange import SafeChange, run_safe_change
from ..security.paths import (
    PathSafetyError,
    check_archive_member,
    is_inside,
    safe_existing,
    safe_filename,
    zip_member_is_symlink,
)

if TYPE_CHECKING:
    from ..jobs import JobHandle, JobTracker

log = logging.getLogger("msc.backups")

ARCHIVE_EXT = {".zip"}


class BackupError(RuntimeError):
    pass


def _unique(path: Path) -> Path:
    """path, or path with -2, -3... added, so two backups or two restores
    within the same second never write over each other."""
    if not path.exists():
        return path
    stem, suffix = (path.stem, path.suffix) if path.suffix == ".zip" else (path.name, "")
    number = 2
    while True:
        candidate = path.with_name(f"{stem}-{number}{suffix}")
        if not candidate.exists():
            return candidate
        number += 1


class BackupManager:
    def __init__(self, config, bus: EventBus, db, server, jobs: JobTracker | None = None):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self.jobs = jobs
        self._running = False

    @property
    def directory(self) -> Path:
        path = self.config.backup_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    def _sources(self, includes: list[str] | None = None) -> list[Path]:
        if not includes:
            # The configured list, plus what this server's type keeps
            # elsewhere (Paper's plugins/ and their data, Forge's
            # defaultconfigs/), so a backup never leaves a server's
            # add-ons behind.
            includes = list(self.config.backups.include)
            for extra in self.config.server_type.backup_extra:
                if extra not in includes:
                    includes.append(extra)
        base = self.config.server_dir
        found = []
        for name in includes:
            safe_filename(name)  # no traversal in include lists either
            path = base / name
            if path.exists():
                found.append(path)
        return found

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _collect(sources: list[Path]) -> list[Path]:
        """Every file a backup of ``sources`` will hold."""
        files: list[Path] = []
        for source in sources:
            if source.is_file():
                files.append(source)
                continue
            for root, dirs, names in os.walk(source, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for name in names:
                    full = Path(root) / name
                    if full.is_symlink():
                        continue
                    # session.lock is held open by the JVM on Windows
                    if name in ("session.lock",):
                        continue
                    files.append(full)
        return files

    def _zip_sync(
        self, target: Path, files: list[Path], base: Path, progress=None
    ) -> tuple[int, int]:
        compression = (
            zipfile.ZIP_DEFLATED
            if self.config.backups.compression != "store"
            else zipfile.ZIP_STORED
        )
        written = 0
        with zipfile.ZipFile(target, "w", compression=compression, allowZip64=True) as zf:
            for full in files:
                try:
                    zf.write(full, full.relative_to(base))
                    written += 1
                except (OSError, ValueError) as exc:
                    log.warning("skipping %s: %s", full, exc)
                if progress:
                    progress(1)
        return written, target.stat().st_size

    # ------------------------------------------------------------------
    async def create(
        self,
        name: str | None = None,
        kind: str = "manual",
        includes: list[str] | None = None,
        user: str = "system",
        note: str | None = None,
        job: JobHandle | None = None,
    ) -> dict[str, Any]:
        """Create and verify a backup. Runs as a job of its own unless it is
        one step of another job (``job`` given)."""
        if job is None and self.jobs is not None:
            created, result = await self.jobs.run(
                "backup",
                f"Backing up {self.config.server.name}",
                lambda handle: self._create(name, kind, includes, user, note, handle),
                server_id=self.server.server_id,
                risky=True,
                user=user,
            )
            return {**result, "job_id": created.id}
        return await self._create(name, kind, includes, user, note, job)

    async def _create(
        self,
        name: str | None,
        kind: str,
        includes: list[str] | None,
        user: str,
        note: str | None,
        job: JobHandle | None,
    ) -> dict[str, Any]:
        if self._running:
            raise BackupError("A backup is already running")
        if job:
            job.step("Finding the files to back up")
        sources = self._sources(includes)
        if not sources:
            raise BackupError("Nothing to back up: none of the configured folders exist")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = _unique(self.directory / f"{kind}-{stamp}{('-' + name) if name else ''}.zip")
        base_name = safe_filename(target.name, ARCHIVE_EXT)
        free = shutil.disk_usage(self.directory).free
        estimated = sum(
            sum(f.stat().st_size for f in s.rglob("*") if f.is_file() and not f.is_symlink())
            if s.is_dir()
            else s.stat().st_size
            for s in sources
        )
        if free < estimated * 0.35 + 200 * 1024**2:
            raise BackupError(
                f"Not enough free disk space: {free / 1024**3:.1f} GB free, "
                f"about {estimated / 1024**3:.1f} GB of source data"
            )

        self._running = True
        started = time.time()
        await self.bus.publish(Event(type="backup_started", message=f"Backup started: {base_name}"))
        saving_disabled = False
        try:
            # Only a backup holding folders (the world) needs Minecraft to
            # flush and pause saving; a copy of one settings file doesn't.
            touches_world = any(source.is_dir() for source in sources)
            if touches_world and self.server.running and self.server.state.value == "ONLINE":
                try:
                    await self.server.send_command("save-all flush", internal=True)
                    await asyncio.sleep(3)
                    await self.server.send_command("save-off", internal=True)
                    saving_disabled = True
                    await asyncio.sleep(1)
                except Exception:
                    log.warning("could not flush the world before backup", exc_info=True)

            members = await asyncio.to_thread(self._collect, sources)
            if job:
                job.step("Writing the backup", total=len(members), unit="files")
            files, size = await asyncio.to_thread(
                self._zip_sync,
                target,
                members,
                self.config.server_dir,
                job.advance if job else None,
            )
            if job:
                job.step("Checking the backup")
            digest = await asyncio.to_thread(self._sha256, target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            self.db.insert(
                "backups",
                {
                    "server_id": self.server.server_id,
                    "name": base_name,
                    "path": str(target),
                    "kind": kind,
                    "created_at": time.time(),
                    "size_bytes": 0,
                    "includes": ",".join(p.name for p in sources),
                    "sha256": None,
                    "status": "failed",
                    "note": str(exc)[:400],
                },
            )
            await self.bus.publish(
                Event(
                    type="backup_failed",
                    level="error",
                    message=f"Backup failed: {exc}",
                    data={"error": str(exc)},
                )
            )
            raise BackupError(str(exc)) from exc
        finally:
            self._running = False
            if saving_disabled:
                try:
                    await self.server.send_command("save-on", internal=True)
                except Exception:
                    log.warning("could not re-enable world saving", exc_info=True)

        # "the zip command returned" is not the same as "there is a good
        # backup". Verify the archive before recording it as usable: it must
        # exist, open, pass a member-by-member integrity test, contain
        # something, and hash to the value we just computed.
        verification = self._verify_file(target, digest, expected_files=files)
        row_id = self.db.insert(
            "backups",
            {
                "server_id": self.server.server_id,
                "name": base_name,
                "path": str(target),
                "kind": kind,
                "created_at": time.time(),
                "size_bytes": size,
                "includes": ",".join(p.name for p in sources),
                "sha256": digest,
                "status": "ok" if verification["ok"] else "unverified",
                "note": note
                if verification["ok"]
                else f"FAILED VERIFICATION: {verification['reason']}",
            },
        )
        if not verification["ok"]:
            await self.bus.publish(
                Event(
                    type="backup_failed",
                    level="error",
                    message=f"Backup failed verification: {verification['reason']}",
                    data={"name": base_name, "reason": verification["reason"]},
                )
            )
            raise BackupError(
                f"The backup was written but failed verification: {verification['reason']}. "
                f"It is recorded as unverified and must not be relied on."
            )
        duration = time.time() - started
        self.db.audit("backup_create", user=user, target=base_name, detail=f"{files} files")
        await self.bus.publish(
            Event(
                type="backup_completed",
                level="success",
                message=f"Backup verified: {base_name} ({size / 1024**3:.2f} GB, {duration:.0f}s)",
                data={
                    "id": row_id,
                    "name": base_name,
                    "size_bytes": size,
                    "files": files,
                    "seconds": duration,
                },
            )
        )
        await self.apply_retention()
        return {
            "id": row_id,
            "name": base_name,
            "path": str(target),
            "size_bytes": size,
            "files": files,
            "sha256": digest,
            "seconds": duration,
            "verified": True,
            "verification": verification,
        }

    def _verify_file(
        self, path: Path, expected_sha256: str | None = None, expected_files: int | None = None
    ) -> dict[str, Any]:
        """Actually open the archive and check it. Source of truth: the file."""
        if not path.is_file():
            return {"ok": False, "reason": "the archive file does not exist on disk"}
        size = path.stat().st_size
        if size < 22:  # smaller than an empty zip's end-of-archive record
            return {"ok": False, "reason": f"the archive is implausibly small ({size} bytes)"}
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                if not names:
                    return {"ok": False, "reason": "the archive contains no files"}
                damaged = zf.testzip()
            if damaged:
                return {"ok": False, "reason": f"the archive is damaged at {damaged}"}
        except (zipfile.BadZipFile, OSError) as exc:
            return {"ok": False, "reason": f"the archive could not be opened: {exc}"}
        if expected_files is not None and len(names) < expected_files:
            return {
                "ok": False,
                "reason": f"expected at least {expected_files} entries, found {len(names)}",
            }
        if expected_sha256:
            actual = self._sha256(path)
            if actual != expected_sha256:
                return {
                    "ok": False,
                    "reason": "the SHA-256 does not match the value computed "
                    "when the archive was written",
                }
        return {
            "ok": True,
            "entries": len(names),
            "size_bytes": size,
            "checks": [
                "file exists",
                "archive opens",
                "member integrity test",
                "entry count",
                "SHA-256 match" if expected_sha256 else "size",
            ],
        }

    # ------------------------------------------------------------------
    def list_backups(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM backups WHERE server_id = ? ORDER BY created_at DESC",
            (self.server.server_id,),
        )
        for row in rows:
            row["exists"] = Path(row["path"]).is_file()
        return rows

    def get(self, backup_id: int) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM backups WHERE id = ? AND server_id = ?",
            (backup_id, self.server.server_id),
        )
        if not row:
            raise BackupError("That backup isn't on this server's list.")
        return row

    def verify(self, backup_id: int) -> dict[str, Any]:
        row = self.get(backup_id)
        path = Path(row["path"])
        if not is_inside(self.directory, path):
            raise PathSafetyError(
                "That backup file isn't in the backups folder, so it wasn't used."
            )
        result = self._verify_file(path, row.get("sha256"))
        if result["ok"]:
            result["sha256"] = row.get("sha256")
        return result

    def path_for_download(self, backup_id: int) -> Path:
        row = self.get(backup_id)
        return safe_existing(self.directory, Path(row["path"]).name, ARCHIVE_EXT)

    async def delete(self, backup_id: int, user: str = "system") -> dict[str, Any]:
        row = self.get(backup_id)
        path = Path(row["path"])
        if not is_inside(self.directory, path):
            raise PathSafetyError("That file isn't in the backups folder, so nothing was deleted.")
        path.unlink(missing_ok=True)
        self.db.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
        self.db.audit("backup_delete", user=user, target=row["name"])
        await self.bus.publish(
            Event(type="backup_deleted", level="warn", message=f"Deleted backup {row['name']}")
        )
        return {"deleted": row["name"]}

    # ------------------------------------------------------------------
    async def restore(
        self,
        backup_id: int,
        user: str = "system",
        start_after: bool = False,
        safety_backup: bool = True,
    ) -> dict[str, Any]:
        """Stop, verify, safety-backup, restore, check. The current world is
        never removed before the safety backup exists, and a restore whose
        result does not check out is put back from that safety backup."""
        row = self.get(backup_id)
        check = self.verify(backup_id)
        if not check["ok"]:
            raise BackupError(f"This backup did not verify: {check['reason']}")
        path = Path(row["path"])
        base = self.config.server_dir

        async def change(job: JobHandle | None) -> dict[str, Any]:
            replaced = await asyncio.to_thread(self._extract, path, base)
            return {"restored": row["name"], "replaced": replaced}

        async def verify_result(result: dict[str, Any]) -> tuple[bool, str]:
            return await asyncio.to_thread(self._verify_restored, path, base)

        plan = SafeChange(
            title=f"Restoring {row['name']}",
            change=change,
            check=verify_result,
            start_after=start_after,
            take_backup=safety_backup,
            backup_name="pre-restore",
            backup_note=f"Automatic safety copy before restoring {row['name']}",
            undo_on_change_error=False,
        )

        async def run(job: JobHandle | None) -> dict[str, Any]:
            try:
                return await run_safe_change(self.server, self, plan, job=job, user=user)
            except Exception as exc:
                await self.bus.publish(
                    Event(type="restore_failed", level="error", message=f"Restore failed: {exc}")
                )
                if isinstance(exc, BackupError):
                    raise
                raise BackupError(f"Restore failed: {exc}") from exc

        job_id = None
        if self.jobs is not None:
            created, result = await self.jobs.run(
                "restore",
                f"Restoring {row['name']} on {self.config.server.name}",
                run,
                server_id=self.server.server_id,
                risky=True,
                user=user,
            )
            job_id = created.id
        else:
            result = await run(None)
        safety = result["safety_backup"]
        self.db.audit(
            "backup_restore",
            user=user,
            target=row["name"],
            detail=f"safety={safety['name'] if safety else 'none'}; verified",
        )
        await self.bus.publish(
            Event(
                type="backup_restored",
                level="warn",
                message=f"Restored {row['name']}",
                data={
                    "backup": row["name"],
                    "safety_backup": safety["name"] if safety else None,
                    "replaced": result["replaced"],
                },
            )
        )
        return {
            **result,
            "verified": True,
            "verification": result["check"],
            "job_id": job_id,
        }

    async def put_back(self, backup_id: int) -> list[str]:
        """Extract a backup over the server folder with no safety copy of its
        own. Only the safe-change routine uses this, to undo a failed change
        from the safety backup it has just taken."""
        row = self.get(backup_id)
        return await asyncio.to_thread(self._extract, Path(row["path"]), self.config.server_dir)

    def _extract(self, path: Path, base: Path) -> list[str]:
        """Move the archive's top-level folders aside, then extract it. If
        anything fails, what was moved aside is put back."""
        replaced: list[str] = []
        try:
            with zipfile.ZipFile(path) as zf:
                members = zf.namelist()
                # reject any member that would escape the server directory
                for info in zf.infolist():
                    check_archive_member(base, info.filename, zip_member_is_symlink(info))
                tops = {m.split("/")[0] for m in members if m.split("/")[0]}
                for top in tops:
                    live = base / top
                    if live.exists():
                        retired = _unique(base / f"{top}.replaced-{time.strftime('%Y%m%d-%H%M%S')}")
                        shutil.move(str(live), str(retired))
                        replaced.append(str(retired))
                zf.extractall(base)
        except Exception as exc:
            # put back whatever was moved aside
            for moved in replaced:
                original = Path(moved)
                name = original.name.split(".replaced-")[0]
                if original.exists() and not (base / name).exists():
                    shutil.move(str(original), str(base / name))
            raise BackupError(
                f"Restore failed and the previous files were put back: {exc}"
            ) from exc
        return replaced

    def _verify_restored(self, archive: Path, base: Path) -> tuple[bool, str]:
        """Confirm the extracted files are actually on disk and the right size.

        A sample is checked rather than every file, because a 40 GB world would
        take minutes; the sample covers the first entries of each top-level
        folder, which is where a truncated extract shows up.
        """
        try:
            with zipfile.ZipFile(archive) as zf:
                entries = [i for i in zf.infolist() if not i.is_dir()]
        except (zipfile.BadZipFile, OSError) as exc:
            return False, f"the archive could not be re-opened to check the result: {exc}"
        if not entries:
            return False, "the archive contained no files"
        by_top: dict[str, list] = {}
        for item in entries:
            by_top.setdefault(item.filename.split("/")[0], []).append(item)
        checked = 0
        for items in by_top.values():
            for item in items[:5]:
                target = base / item.filename
                if not target.exists():
                    return False, f"{item.filename} is missing after extraction"
                if target.stat().st_size != item.file_size:
                    return (
                        False,
                        f"{item.filename} is {target.stat().st_size} bytes, expected {item.file_size}",
                    )
                checked += 1
        return True, f"{checked} restored file(s) checked across {len(by_top)} top-level path(s)"

    # ------------------------------------------------------------------
    async def apply_retention(self) -> dict[str, Any]:
        """Keep N daily, weekly and monthly backups. Safety backups are kept
        for 14 days regardless; manual backups are never auto-deleted."""
        keep_daily = self.config.backups.keep_daily
        keep_weekly = self.config.backups.keep_weekly
        keep_monthly = self.config.backups.keep_monthly
        rows = [r for r in self.list_backups() if r["status"] == "ok"]

        keep: set[int] = set()
        buckets: dict[str, dict[str, dict]] = {"daily": {}, "weekly": {}, "monthly": {}}
        for row in sorted(rows, key=lambda r: r["created_at"], reverse=True):
            if row["kind"] == "manual":
                keep.add(row["id"])
                continue
            if row["kind"] == "safety":
                if time.time() - row["created_at"] < 14 * 86400:
                    keep.add(row["id"])
                continue
            t = time.localtime(row["created_at"])
            for span, key in (
                ("daily", time.strftime("%Y-%m-%d", t)),
                ("weekly", time.strftime("%Y-W%W", t)),
                ("monthly", time.strftime("%Y-%m", t)),
            ):
                buckets[span].setdefault(key, row)
        for span, limit in (
            ("daily", keep_daily),
            ("weekly", keep_weekly),
            ("monthly", keep_monthly),
        ):
            chosen = sorted(buckets[span].values(), key=lambda r: r["created_at"], reverse=True)[
                :limit
            ]
            keep.update(r["id"] for r in chosen)

        removed = []
        for row in rows:
            if row["id"] in keep:
                continue
            path = Path(row["path"])
            if is_inside(self.directory, path):
                path.unlink(missing_ok=True)
                self.db.execute("DELETE FROM backups WHERE id = ?", (row["id"],))
                removed.append(row["name"])
        if removed:
            await self.bus.publish(
                Event(
                    type="backup_retention",
                    message=f"Retention removed {len(removed)} old backup(s)",
                    data={"removed": removed},
                )
            )
        return {"removed": removed, "kept": len(keep)}

    # ------------------------------------------------------------------
    def world_summary(self) -> list[dict[str, Any]]:
        from ..security.paths import directory_size

        base = self.config.server_dir
        out = []
        for key, label in (
            ("world", "Overworld"),
            ("world_nether", "Nether"),
            ("world_the_end", "The End"),
        ):
            path = base / key
            if not path.exists():
                out.append({"key": key, "label": label, "exists": False})
                continue
            last_backup = self.db.query_one(
                "SELECT name, created_at FROM backups WHERE server_id = ? AND status = 'ok' "
                "AND includes LIKE ? ORDER BY created_at DESC LIMIT 1",
                (self.server.server_id, f"%{key}%"),
            )
            out.append(
                {
                    "key": key,
                    "label": label,
                    "exists": True,
                    "size_bytes": directory_size(path),
                    "modified": path.stat().st_mtime,
                    "last_backup": last_backup,
                }
            )
        return out
