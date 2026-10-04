"""The Fabric mod manager.

Everything that touches the mods folder goes through this class, and every
write is:

  * confined to the mods folder by agent.security.paths
  * limited to .jar (and .jar.disabled) files
  * recorded in mod_history with actor, source URL and SHA-256
  * reversible - removals go to a trash folder, updates keep the old jar

Nothing here executes a downloaded file. The only program that ever reads a
mod jar is the Minecraft server itself, when the operator starts it.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from ..events import Event, EventBus
from ..security.paths import (
    PathSafetyError,
    assert_not_symlink,
    is_inside,
    safe_filename,
    safe_join,
)
from . import checks
from .jarinfo import DISABLED_SUFFIX, ModInfo, read_mod_jar, sha256_file, version_satisfies
from .modrinth import ModrinthClient, ModrinthError
from .dependencies import DependencyResolver

log = logging.getLogger("msc.mods")

JAR_EXT = {".jar"}


class ModError(RuntimeError):
    """Operator-visible mod management problem."""


class ModManager:
    def __init__(self, config, bus: EventBus, db, server, backups=None):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self.backups = backups
        self.modrinth = ModrinthClient(config)
        self.deps = DependencyResolver(self)
        self._cache: tuple[float, list[ModInfo]] | None = None

    # ------------------------------------------------------------------
    # directories
    # ------------------------------------------------------------------
    @property
    def mods_dir(self) -> Path:
        path = self.config.mods_dir
        if not self.config.server_dir_configured:
            raise ModError(
                "The Minecraft server folder is not set. "
                "Set server.directory in config/config.yaml."
            )
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def backup_dir(self) -> Path:
        path = self.config.mod_backup_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def trash_dir(self) -> Path:
        path = self.config.mod_trash_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    def scan(self, use_cache: bool = False, max_age: float = 10.0) -> list[ModInfo]:
        if use_cache and self._cache and time.time() - self._cache[0] < max_age:
            return self._cache[1]
        mods: list[ModInfo] = []
        for entry in sorted(self.mods_dir.iterdir()):
            if not entry.is_file() or entry.is_symlink():
                continue
            name = entry.name
            if not (name.endswith(".jar") or name.endswith(".jar" + DISABLED_SUFFIX)):
                continue
            mods.append(read_mod_jar(entry))
        self._cache = (time.time(), mods)
        return mods

    def list_installed(self, use_cache: bool = False) -> list[dict[str, Any]]:
        mods = self.scan(use_cache=use_cache)
        issues = self.check_all(mods)
        by_file = {i["filename"]: i for i in issues["per_mod"]}
        result = []
        for mod in mods:
            row = mod.to_dict()
            row["issues"] = by_file.get(mod.filename, {}).get("issues", [])
            row["status"] = by_file.get(mod.filename, {}).get("status", "ok")
            latest = self.db.query_one(
                "SELECT version, created_at FROM mod_versions WHERE server_id = ? AND mod_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (self.server.server_id, mod.mod_id),
            )
            row["has_history"] = bool(latest)
            update = self.db.get_setting(f"mod_update:{mod.mod_id}")
            if update and update.get("installed_version") == mod.version:
                row["update_available"] = update
            else:
                row["update_available"] = None
            result.append(row)
        return result

    def find(self, filename: str) -> ModInfo:
        name = safe_filename(filename)
        for mod in self.scan():
            if mod.filename == name:
                return mod
        raise ModError(f"{filename} is not in the mods folder")

    def find_by_id(self, mod_id: str) -> ModInfo | None:
        for mod in self.scan():
            if mod.mod_id == mod_id:
                return mod
        return None

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    def check_all(self, mods: list[ModInfo] | None = None) -> dict[str, Any]:
        """Dependency, duplicate and compatibility checks across the folder.

        Limits are stated openly: this reads declared metadata only. Two mods
        can still conflict at runtime with nothing in their metadata to say so,
        and this checker cannot see that.
        """
        mods = mods if mods is not None else self.scan()
        enabled = [m for m in mods if m.enabled]
        installed = {m.mod_id: m for m in enabled}
        mc_version = self.server.mc_version
        loader_version = self.server.loader_version

        per_mod: list[dict[str, Any]] = []
        problems: list[dict[str, Any]] = checks.duplicate_ids(enabled)
        for mod in mods:
            issues = checks.jar_issues(mod)
            if not mod.enabled:
                per_mod.append(
                    {
                        "filename": mod.filename,
                        "mod_id": mod.mod_id,
                        "status": "disabled",
                        "issues": issues,
                    }
                )
                continue
            issues += checks.dependency_issues(mod, installed, mc_version, loader_version)
            issues += checks.breaks_issues(mod, installed)
            per_mod.append(
                {
                    "filename": mod.filename,
                    "mod_id": mod.mod_id,
                    "status": checks.status_of(issues),
                    "issues": issues,
                }
            )
            problems.extend(
                {**i, "mod": mod.name, "filename": mod.filename}
                for i in issues
                if i["severity"] == "error"
            )

        return {
            "per_mod": per_mod,
            "problems": problems,
            "minecraft_version": mc_version,
            "fabric_loader": loader_version,
            "checked_at": time.time(),
            "claim": (
                "No declared conflicts detected"
                if not problems
                else f"{len(problems)} declared problem(s) detected"
            ),
            "claim_note": (
                "'No declared conflicts detected' is not the same as 'no conflicts "
                "exist'. Only metadata was read; nothing was executed or tested."
            ),
            "limitations": [
                "Only declared metadata is checked (fabric.mod.json).",
                "Mods can still conflict at runtime with nothing declared in their metadata.",
                "Minecraft and Fabric versions are read from the server console, so they are "
                "only known after the server has started at least once.",
            ],
        }

    def missing_dependencies(self) -> list[dict[str, Any]]:
        checks = self.check_all()
        return [p for p in checks["problems"] if p["kind"] == "missing_dependency"]

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------
    def compatibility_verdict(
        self, modrinth_version: dict | None, mod: ModInfo | None = None
    ) -> dict[str, Any]:
        """How confident we are that a mod will work here.

        Four verdicts, and none of them is "it works":

          verified_metadata  the mod's own fabric.mod.json declares this
                             Minecraft version, and Modrinth agrees
          likely             Modrinth lists this Minecraft version, but the
                             jar's own metadata could not confirm it
          unknown            the server's Minecraft version has not been
                             observed yet, so nothing can be compared
          incompatible       a declared requirement is not met

        Listing on Modrinth is a publisher's claim, not a test result, so it
        never produces better than "likely" on its own.
        """
        mc_version = self.server.mc_version
        if not mc_version:
            return {
                "verdict": "unknown",
                "detail": (
                    "The server's Minecraft version has not been observed yet. It is read "
                    "from the console on first start, so compatibility cannot be checked."
                ),
            }
        declared = None
        if mod and mod.minecraft_range:
            declared = version_satisfies(mc_version, mod.minecraft_range)
        listed = None
        if modrinth_version:
            listed = mc_version in (modrinth_version.get("game_versions") or [])
        if declared is False:
            return {
                "verdict": "incompatible",
                "detail": f"The jar declares it needs Minecraft {mod.minecraft_range}, "
                f"but this server runs {mc_version}.",
            }
        if declared is True and listed is not False:
            return {
                "verdict": "verified_metadata",
                "detail": f"The jar declares support for {mod.minecraft_range}, which "
                f"includes {mc_version}. Metadata only - not a test.",
            }
        if listed:
            return {
                "verdict": "likely",
                "detail": f"Modrinth lists this build for Minecraft {mc_version}, but the "
                f"jar's own metadata could not confirm it. That is the "
                f"publisher's claim, not a test result.",
            }
        return {
            "verdict": "unknown",
            "detail": "Neither the jar metadata nor Modrinth confirmed this Minecraft version.",
        }

    def record(
        self,
        action: str,
        user: str,
        mod: ModInfo | None = None,
        *,
        mod_id: str | None = None,
        mod_name: str | None = None,
        old_version: str | None = None,
        new_version: str | None = None,
        source: str | None = None,
        sha256: str | None = None,
        result: str = "ok",
        detail: str | None = None,
    ) -> int:
        return self.db.insert(
            "mod_history",
            {
                "server_id": self.server.server_id,
                "ts": time.time(),
                "user": user,
                "action": action,
                "mod_id": mod_id or (mod.mod_id if mod else None),
                "mod_name": mod_name or (mod.name if mod else None),
                "old_version": old_version,
                "new_version": new_version or (mod.version if mod else None),
                "source": source,
                "sha256": sha256 or (mod.sha256 if mod else None),
                "result": result,
                "detail": detail,
            },
        )

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM mod_history WHERE server_id = ? ORDER BY ts DESC LIMIT ?",
            (self.server.server_id, limit),
        )

    # ------------------------------------------------------------------
    # archive / versions
    # ------------------------------------------------------------------
    def archive(self, path: Path, mod: ModInfo, source: str | None = None) -> Path:
        """Copy a jar into mod-backups/<mod_id>/<timestamp>-<filename>."""
        folder = self.backup_dir / (mod.mod_id or "unknown")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base_name = path.name.replace(DISABLED_SUFFIX, "")
        target = folder / f"{stamp}-{base_name}"
        # Two archives can land in the same second (pre-update then post-update,
        # or archive-then-rollback). Never let the second one overwrite the
        # first: an archive that silently changed content would defeat the
        # SHA-256 check that rollback relies on.
        counter = 1
        while target.exists():
            target = folder / f"{stamp}-{counter}-{base_name}"
            counter += 1
        shutil.copy2(path, target)
        self.db.insert(
            "mod_versions",
            {
                "server_id": self.server.server_id,
                "mod_id": mod.mod_id,
                "version": mod.version,
                "filename": base_name,
                "archive_path": str(target),
                "sha256": mod.sha256 or sha256_file(target),
                "source": source,
                "created_at": time.time(),
            },
        )
        return target

    def versions_for(self, mod_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM mod_versions WHERE server_id = ? AND mod_id = ? ORDER BY created_at DESC",
            (self.server.server_id, mod_id),
        )
        current = self.find_by_id(mod_id)
        for row in rows:
            row["is_current"] = bool(current and current.version == row["version"])
            row["exists"] = Path(row["archive_path"]).is_file()
        return rows

    # ------------------------------------------------------------------
    # write operations
    # ------------------------------------------------------------------
    def _require_server_offline(self, action: str) -> None:
        if self.server.state.value == "RESTART_PENDING":
            # The countdown could restart the server while a jar is half-written.
            raise ModError(f"An automatic restart is counting down. Cancel it before you {action}.")
        if self.server.running:
            raise ModError(
                f"The server is {self.server.state.value}. Stop it before you {action}: "
                "Fabric locks mod jars while it runs and changing them mid-session can corrupt state."
            )

    async def _emit(self, type_: str, message: str, level: str = "info", **data) -> None:
        await self.bus.publish(Event(type=type_, message=message, level=level, data=data))

    def preview_install(self, mod_id_or_slug: str) -> dict[str, Any]:
        existing = self.find_by_id(mod_id_or_slug)
        return {"already_installed": existing.to_dict() if existing else None}

    async def install_from_modrinth(
        self,
        project: str,
        user: str,
        version_id: str | None = None,
        minecraft_version: str | None = None,
        allow_replace: bool = False,
        install_dependencies: bool = False,
    ) -> dict[str, Any]:
        """Download and install a mod. Returns a report of what changed."""
        self._require_server_offline("install a mod")
        mc_version = minecraft_version or self.server.mc_version

        if version_id:
            version = await self.modrinth.version(version_id)
        else:
            version = await self.modrinth.latest_for(project, mc_version)
        if not version:
            raise ModError(
                f"No Fabric build of '{project}' was published"
                + (f" for Minecraft {mc_version}" if mc_version else "")
            )
        if mc_version and mc_version not in version["game_versions"]:
            raise ModError(
                f"{version['version_number']} supports {', '.join(version['game_versions'][:6])}, "
                f"not {mc_version}. Pick a different version."
            )
        if "fabric" not in [l.lower() for l in version["loaders"]]:
            raise ModError(f"This file targets {', '.join(version['loaders'])}, not Fabric")

        filename = version["file"]["filename"]
        target = safe_join(self.mods_dir, filename, allowed_extensions=JAR_EXT)
        if target.exists() and not allow_replace:
            raise ModError(
                f"{filename} is already in the mods folder. "
                "Nothing was overwritten. Use the update action, or confirm replacement."
            )

        data, filename, sha256 = await self.modrinth.download(version)
        temp = self.mods_dir / f".{filename}.part"
        temp.write_bytes(data)
        try:
            info = read_mod_jar(temp, compute_hash=False)
            if info.loader == "forge":
                raise ModError("The downloaded file is a Forge mod. It was discarded.")
            if info.loader == "unknown":
                raise ModError("The downloaded file has no fabric.mod.json. It was discarded.")
            replaced = None
            if target.exists():
                assert_not_symlink(target)
                old = read_mod_jar(target)
                self.archive(target, old, source="replaced-on-install")
                replaced = old.to_dict()
                target.unlink()
            temp.replace(target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)

        installed = read_mod_jar(target)
        installed.sha256 = sha256
        self.archive(target, installed, source=version["file"]["url"])
        self.record(
            "install",
            user,
            installed,
            new_version=installed.version,
            source=version["file"]["url"],
            sha256=sha256,
            detail=f"Modrinth {version['version_number']} ({version['release_type']})",
        )
        self.db.set_setting(
            f"mod_source:{installed.mod_id}",
            {
                "modrinth_project": version.get("project_id") or project,
                "version_id": version["version_id"],
            },
        )
        self._cache = None
        await self._emit(
            "mod_installed",
            f"Installed {installed.name} {installed.version}",
            level="success",
            mod=installed.to_dict(),
            source="modrinth",
        )

        report: dict[str, Any] = {
            "installed": installed.to_dict(),
            # Writing a jar into the mods folder is not the same as Fabric
            # loading it. That is only known after the server has started and
            # reported the mod, so it stays unverified until then.
            "loaded_by_minecraft": "not verified",
            "loaded_detail": (
                "The file is in the mods folder. Start the server to find out "
                "whether Fabric loads it."
            ),
            "compatibility": self.compatibility_verdict(version, installed),
            "replaced": replaced,
            "sha256": sha256,
            "source": version["file"]["url"],
            "release_type": version["release_type"],
            "dependencies_required": [],
            "dependencies_installed": [],
        }

        # Dependencies are planned from this version's Modrinth metadata and
        # installed through the same verified path; see dependencies.py.
        if install_dependencies:
            outcome = await self.deps.install(None, user)
            report["dependencies_installed"] = [
                r for r in outcome["results"] if r["result"] == "installed"
            ]
            report["dependencies_failed"] = [
                r for r in outcome["results"] if r["result"] == "failed"
            ]
            report["dependencies_required"] = [
                {"mod_id": g["mod_id"], "title": g["name"], "installed": False}
                for g in outcome["still_missing"]
            ]
        else:
            report["dependencies_required"] = [
                {
                    "mod_id": g["mod_id"],
                    "title": g["name"],
                    "installed": False,
                    "range_text": g["range_text"],
                }
                for g in self.deps.analyse()["items"]
                if g["status"] == "missing" and g["kind"] == "required"
            ]
        return report

    async def install_local_file(
        self, filename: str, data: bytes, user: str, allow_replace: bool = False
    ) -> dict[str, Any]:
        """Install an uploaded jar. Same rules as a Modrinth install."""
        self._require_server_offline("install a mod")
        safe_filename(filename, JAR_EXT)
        if not data.startswith(b"PK"):
            raise ModError("That file is not a jar archive")
        if len(data) > 300 * 1024 * 1024:
            raise ModError("That file is larger than the 300 MB limit")
        target = safe_join(self.mods_dir, filename, allowed_extensions=JAR_EXT)
        if target.exists() and not allow_replace:
            raise ModError(f"{filename} already exists. Nothing was overwritten.")
        temp = self.mods_dir / f".{filename}.part"
        temp.write_bytes(data)
        try:
            info = read_mod_jar(temp, compute_hash=True)
            if info.loader in ("forge", "unknown"):
                raise ModError(
                    "That jar has no fabric.mod.json, so it is not a Fabric mod. It was discarded."
                )
            if target.exists():
                old = read_mod_jar(target)
                self.archive(target, old, source="replaced-on-upload")
                target.unlink()
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        installed = read_mod_jar(target)
        self.archive(target, installed, source="uploaded")
        self.record("install", user, installed, source="upload", detail=f"Uploaded {filename}")
        self._cache = None
        await self._emit(
            "mod_installed",
            f"Installed {installed.name} {installed.version} from a file",
            level="success",
            mod=installed.to_dict(),
            source="upload",
        )
        return {
            "installed": installed.to_dict(),
            "loaded_by_minecraft": "not verified",
            "loaded_detail": (
                "The file is in the mods folder. Start the server to find out "
                "whether Fabric loads it."
            ),
        }

    def removal_impact(self, filename: str) -> dict[str, Any]:
        """What breaks if this mod goes away."""
        mod = self.find(filename)
        dependents = []
        for other in self.scan():
            if other.filename == mod.filename or not other.enabled:
                continue
            for dep in other.dependencies:
                if dep.mod_id == mod.mod_id and dep.kind == "depends":
                    dependents.append(
                        {
                            "name": other.name,
                            "mod_id": other.mod_id,
                            "filename": other.filename,
                            "requires": dep.version_range,
                        }
                    )
        return {
            "mod": mod.to_dict(),
            "dependents": dependents,
            "warning": (
                f"{len(dependents)} installed mod(s) declare {mod.mod_id} as a required dependency. "
                "Removing it may stop the server from starting."
            )
            if dependents
            else None,
        }

    async def remove(self, filename: str, user: str, backup: bool = True) -> dict[str, Any]:
        self._require_server_offline("remove a mod")
        mod = self.find(filename)
        path = Path(mod.path)
        assert_not_symlink(path)
        if not is_inside(self.mods_dir, path):
            raise PathSafetyError("That file is not inside the mods folder")
        archived = None
        if backup:
            archived = str(self.archive(path, mod, source="removed"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        trash_target = self.trash_dir / f"{stamp}-{path.name}"
        shutil.move(str(path), str(trash_target))
        self.record(
            "remove",
            user,
            mod,
            old_version=mod.version,
            source="local",
            detail=f"Moved to {trash_target.name}",
        )
        self._cache = None
        await self._emit(
            "mod_removed", f"Removed {mod.name} {mod.version}", level="warn", mod=mod.to_dict()
        )
        return {"removed": mod.to_dict(), "archived": archived, "trash": str(trash_target)}

    async def set_enabled(self, filename: str, enabled: bool, user: str) -> dict[str, Any]:
        self._require_server_offline("enable or disable a mod")
        mod = self.find(filename)
        path = Path(mod.path)
        assert_not_symlink(path)
        if enabled and mod.enabled:
            return {"mod": mod.to_dict(), "changed": False}
        if not enabled and not mod.enabled:
            return {"mod": mod.to_dict(), "changed": False}
        if enabled:
            new_name = path.name[: -len(DISABLED_SUFFIX)]
        else:
            new_name = path.name + DISABLED_SUFFIX
        target = self.mods_dir / new_name
        if not is_inside(self.mods_dir, target):
            raise PathSafetyError("Refusing to write outside the mods folder")
        if target.exists():
            raise ModError(f"{new_name} already exists in the mods folder")
        path.rename(target)
        self._cache = None
        updated = read_mod_jar(target)
        action = "enable" if enabled else "disable"
        self.record(action, user, updated, detail=f"{path.name} -> {new_name}")
        await self._emit(
            f"mod_{action}d",
            f"{'Enabled' if enabled else 'Disabled'} {updated.name}",
            mod=updated.to_dict(),
        )
        return {"mod": updated.to_dict(), "changed": True}

    # ------------------------------------------------------------------
    # updates
    # ------------------------------------------------------------------
    async def check_updates(self, minecraft_version: str | None = None) -> list[dict[str, Any]]:
        mc_version = minecraft_version or self.server.mc_version
        updates: list[dict[str, Any]] = []
        for mod in self.scan():
            if not mod.enabled:
                continue
            source = self.db.get_setting(f"mod_source:{mod.mod_id}") or {}
            project = source.get("modrinth_project") or mod.modrinth_project or mod.mod_id
            try:
                latest = await self.modrinth.latest_for(project, mc_version)
            except ModrinthError:
                continue
            if not latest:
                continue
            if latest["version_number"] and latest["version_number"] != mod.version:
                entry = {
                    "mod_id": mod.mod_id,
                    "name": mod.name,
                    "filename": mod.filename,
                    "installed_version": mod.version,
                    "latest_version": latest["version_number"],
                    "version_id": latest["version_id"],
                    "release_type": latest["release_type"],
                    "game_versions": latest["game_versions"],
                    "project": project,
                    "changelog": latest.get("changelog", "")[:400],
                }
                updates.append(entry)
                self.db.set_setting(f"mod_update:{mod.mod_id}", entry)
            else:
                self.db.set_setting(f"mod_update:{mod.mod_id}", None)
        self.db.set_setting("mod_updates_checked_at", time.time())
        return updates

    async def update(
        self, filename: str, user: str, version_id: str | None = None
    ) -> dict[str, Any]:
        self._require_server_offline("update a mod")
        mod = self.find(filename)
        old_path = Path(mod.path)
        archived = self.archive(old_path, mod, source="pre-update")
        source = self.db.get_setting(f"mod_source:{mod.mod_id}") or {}
        project = source.get("modrinth_project") or mod.modrinth_project or mod.mod_id
        if version_id:
            version = await self.modrinth.version(version_id)
        else:
            version = await self.modrinth.latest_for(project, self.server.mc_version)
        if not version:
            raise ModError(f"No newer Fabric build of {mod.name} was found on Modrinth")

        data, new_filename, sha256 = await self.modrinth.download(version)
        target = safe_join(self.mods_dir, new_filename, allowed_extensions=JAR_EXT)
        temp = self.mods_dir / f".{new_filename}.part"
        temp.write_bytes(data)
        try:
            probe = read_mod_jar(temp, compute_hash=False)
            if probe.loader != "fabric":
                raise ModError("The downloaded file is not a Fabric mod. Nothing was changed.")
            old_path.unlink()
            temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True)
            if not old_path.exists():  # put the old jar back
                shutil.copy2(archived, old_path)
            raise
        installed = read_mod_jar(target)
        installed.sha256 = sha256
        self.archive(target, installed, source=version["file"]["url"])
        self.record(
            "update",
            user,
            installed,
            old_version=mod.version,
            new_version=installed.version,
            source=version["file"]["url"],
            sha256=sha256,
        )
        self.db.set_setting(
            f"mod_source:{installed.mod_id}",
            {
                "modrinth_project": version.get("project_id") or project,
                "version_id": version["version_id"],
            },
        )
        self.db.set_setting(f"mod_update:{installed.mod_id}", None)
        self._cache = None
        await self._emit(
            "mod_updated",
            f"Updated {installed.name}: {mod.version} to {installed.version}",
            level="success",
            mod=installed.to_dict(),
            previous=mod.version,
        )
        return {
            "updated": installed.to_dict(),
            "previous_version": mod.version,
            "rollback_archive": str(archived),
            "loaded_by_minecraft": "not verified",
            "loaded_detail": (
                "The new jar is in place. Start the server to find out whether "
                "Fabric loads it. If startup fails, roll back from History."
            ),
        }

    async def rollback(self, mod_id: str, archive_path: str, user: str) -> dict[str, Any]:
        self._require_server_offline("roll a mod back")
        row = self.db.query_one(
            "SELECT * FROM mod_versions WHERE server_id = ? AND mod_id = ? AND archive_path = ?",
            (self.server.server_id, mod_id, archive_path),
        )
        if not row:
            raise ModError("That archived version is not in this server's mod history")
        source = Path(row["archive_path"])
        if not source.is_file():
            raise ModError("The archived jar file is missing from mod-backups")
        if not is_inside(self.backup_dir, source):
            raise PathSafetyError("The archive path is outside the mod backup folder")
        if row.get("sha256"):
            actual = sha256_file(source)
            if actual != row["sha256"]:
                raise ModError(
                    "The archived jar no longer matches its recorded SHA-256. Refusing to use it."
                )

        current = self.find_by_id(mod_id)
        previous_version = current.version if current else None
        if current:
            current_path = Path(current.path)
            self.archive(current_path, current, source="pre-rollback")
            current_path.unlink()
        target = safe_join(self.mods_dir, row["filename"], allowed_extensions=JAR_EXT)
        shutil.copy2(source, target)
        restored = read_mod_jar(target)
        self.record(
            "rollback",
            user,
            restored,
            old_version=previous_version,
            new_version=restored.version,
            source=str(source),
        )
        self._cache = None
        await self._emit(
            "mod_rolled_back",
            f"Rolled {restored.name} back to {restored.version}",
            level="warn",
            mod=restored.to_dict(),
            previous=previous_version,
        )
        return {"restored": restored.to_dict(), "previous_version": previous_version}

    async def close(self) -> None:
        await self.modrinth.close()
