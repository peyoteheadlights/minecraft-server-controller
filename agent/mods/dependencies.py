"""Mod dependencies: what is missing, in words a person can act on, and how
to install it safely.

Two sources of truth, used for what each is good at:

  * the installed jars' own fabric.mod.json - authoritative for what a mod
    actually needs (analyse())
  * Modrinth - for a readable name, a page link, a downloadable version that
    satisfies the required range, and that version's own dependencies, so a
    whole chain (A needs B needs C) can be planned before anything is
    downloaded (plan())

Safety rules for installing:
  * nothing is installed whose mod id is already present, enabled or not -
    that would create a duplicate; a present-but-wrong version is reported
    for the user to decide, never silently replaced or downgraded
  * identifiers are validated before they are used in any request
  * every download goes through ModManager.install_from_modrinth, which keeps
    its checksum verification, path safety, archiving and no-overwrite rules
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .jarinfo import range_satisfies
from .modrinth import ModrinthError, ModrinthNotFound

log = logging.getLogger("msc.mods.deps")

# Dependencies on the platform (Minecraft, Java, the loader itself) rather
# than on another mod, for every loader's way of naming them.
PLATFORM_IDS = {
    "minecraft",
    "java",
    "fabricloader",
    "fabric-loader",
    "quilt_loader",
    "forge",
    "neoforge",
    "fml",
    "javafml",
}
REQUIRED_KINDS = {"depends"}
OPTIONAL_KINDS = {"recommends", "suggests"}
MAX_DEPTH = 6
CACHE_SECONDS = 7 * 86400

# Mod ids that are published on Modrinth under a different project.
ALIASES = {"fabric": "fabric-api"}
FABRIC_API_MODULE_RE = re.compile(r"^fabric-[a-z0-9-]+-(api|v\d+)(-v\d+)?$|^fabric-api-base$")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9]{8}$")


class DependencyError(RuntimeError):
    pass


def valid_identifier(value: str) -> bool:
    """A mod id, Modrinth slug or project id - nothing that could reshape a URL."""
    value = str(value or "")
    return bool(SLUG_RE.match(value) or PROJECT_ID_RE.match(value))


def modrinth_slug_for(mod_id: str) -> str:
    if mod_id in ALIASES:
        return ALIASES[mod_id]
    if FABRIC_API_MODULE_RE.match(mod_id):
        return "fabric-api"
    return mod_id


def pretty_name(mod_id: str) -> str:
    """A readable fallback name when Modrinth cannot be asked."""
    known = {
        "fabric-api": "Fabric API",
        "fabricloader": "Fabric Loader",
        "minecraft": "Minecraft",
        "java": "Java",
        "cloth-config": "Cloth Config",
        "modmenu": "Mod Menu",
    }
    if mod_id in known:
        return known[mod_id]
    return " ".join(part.capitalize() for part in re.split(r"[-_]", mod_id) if part) or mod_id


def describe_range(spec: str | None) -> str:
    """Turn a Fabric version range into words.

    ">=1.2" -> "1.2 or newer", "*" -> "Any version". Unrecognised syntax is
    shown as written rather than guessed at.
    """
    spec = str(spec or "").strip()
    if spec in ("", "*", "any"):
        return "Any version"
    alternatives = []
    for alternative in spec.split("||"):
        parts = []
        for clause in alternative.split():
            clause = clause.strip()
            if not clause:
                continue
            for op, words in (
                (">=", "{} or newer"),
                ("<=", "{} or older"),
                (">", "newer than {}"),
                ("<", "older than {}"),
                ("=", "exactly {}"),
            ):
                if clause.startswith(op) and clause[len(op) :]:
                    parts.append(words.format(clause[len(op) :]))
                    break
            else:
                if clause.startswith("~") and clause[1:]:
                    base = clause[1:].split(".")
                    series = ".".join(base[:2]) if len(base) >= 2 else base[0]
                    parts.append(f"{clause[1:]} or a newer {series}.x release")
                elif clause.startswith("^") and clause[1:]:
                    major = clause[1:].split(".")[0]
                    parts.append(f"{clause[1:]} or a newer {major}.x release")
                elif clause.endswith((".x", ".*")):
                    parts.append(f"any {clause[:-2]} release")
                elif any(ch in clause for ch in "[]()"):
                    parts.append(clause)
                else:
                    parts.append(f"exactly {clause}")
        if parts:
            alternatives.append(" and ".join(parts))
    return " or ".join(alternatives) if alternatives else spec


Range = str | tuple[str, str]  # a range, or (range, syntax) as jarinfo reads it


def range_text(spec: Range) -> str:
    return spec if isinstance(spec, str) else spec[0]


def combined_satisfies(version: str, ranges: list[Range]) -> bool | None:
    """True if every range accepts the version, False if any rejects it, None
    if at least one range could not be evaluated."""
    verdicts = [
        range_satisfies(version, *((r, "fabric") if isinstance(r, str) else r))
        for r in ranges
        if range_text(r)
    ]
    if any(v is False for v in verdicts):
        return False
    if any(v is None for v in verdicts):
        return None
    return True


class DependencyResolver:
    def __init__(self, manager):
        self.manager = manager
        self.db = manager.db
        self.server = manager.server

    @property
    def modrinth(self):
        return self.manager.modrinth

    # ------------------------------------------------------------------ local analysis
    def _installed_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for mod in self.manager.scan():
            entry = {"mod": mod, "enabled": mod.enabled}
            index.setdefault(mod.mod_id, entry)
            source = self.db.get_setting(f"mod_source:{mod.mod_id}") or {}
            for alias in {mod.modrinth_project, source.get("modrinth_project")} - {None}:
                index.setdefault(str(alias), entry)
        return index

    def analyse(self) -> dict[str, Any]:
        """Every dependency of every enabled mod, grouped by the mod it needs.

        Statuses: satisfied, missing, disabled (present but turned off),
        incompatible (present at a version outside the range), unverified
        (the range syntax could not be checked), and for Minecraft / Fabric
        Loader / Java: platform_ok or platform_incompatible.
        """
        installed = self._installed_index()
        groups = self._group_dependencies(self.manager.scan())
        for dep_id, group in groups.items():
            ranges: list[Range] = [(r["range"], r["syntax"]) for r in group["required_by"]]
            group["range_text"] = " and ".join(
                sorted({describe_range(range_text(r)) for r in ranges})
            )
            if group["platform"]:
                self._judge_platform(group, self._platform_version(dep_id), ranges)
            else:
                self._judge_mod(group, self._find_installed(dep_id, installed), ranges)
        items = sorted(groups.values(), key=lambda g: (g["kind"] != "required", g["name"].lower()))
        return self._report(items)

    def _platform_version(self, dep_id: str) -> str | None:
        """What the server runs, as read from its console: Minecraft, or the
        loader itself (Fabric Loader, Quilt Loader, Forge, NeoForge)."""
        if dep_id == "minecraft":
            return self.server.mc_version
        if dep_id == "java":
            return None
        return self.server.loader_version

    @staticmethod
    def _group_dependencies(mods) -> dict[str, dict[str, Any]]:
        """One entry per needed mod id, listing every enabled mod that needs it."""
        groups: dict[str, dict[str, Any]] = {}
        for mod in mods:
            if not mod.enabled:
                continue
            for dep in mod.dependencies:
                if dep.kind not in REQUIRED_KINDS | OPTIONAL_KINDS:
                    continue
                kind = "required" if dep.kind in REQUIRED_KINDS else "optional"
                group = groups.setdefault(
                    dep.mod_id,
                    {
                        "mod_id": dep.mod_id,
                        "name": pretty_name(dep.mod_id),
                        "kind": kind,
                        "platform": dep.mod_id in PLATFORM_IDS,
                        "required_by": [],
                        "status": None,
                        "installed_version": None,
                        "modrinth": None,
                    },
                )
                if kind == "required":
                    group["kind"] = "required"  # required by anyone wins over optional
                group["required_by"].append(
                    {
                        "mod_id": mod.mod_id,
                        "name": mod.name,
                        "filename": mod.filename,
                        "range": dep.version_range,
                        "syntax": dep.syntax,
                        "range_text": describe_range(dep.version_range),
                        "kind": kind,
                    }
                )
        return groups

    @staticmethod
    def _find_installed(dep_id: str, installed: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        present = installed.get(dep_id)
        fabric_api = installed.get("fabric-api")
        if (
            present is None
            and dep_id.startswith("fabric-")
            and fabric_api
            and fabric_api["enabled"]
        ):
            present = fabric_api  # Fabric API bundles its modules
        return present

    @staticmethod
    def _judge_platform(group: dict[str, Any], actual: str | None, ranges: list[Range]) -> None:
        """Minecraft, the loader or Java: compare with what the server runs."""
        dep_id = group["mod_id"]
        group["installed_version"] = actual
        if not actual:
            group["status"] = "unverified"
            group["reason"] = (
                f"The {pretty_name(dep_id)} version is not known yet; it is "
                "read from the server console when the server starts."
            )
            return
        verdict = combined_satisfies(actual, ranges)
        group["status"] = {True: "platform_ok", False: "platform_incompatible", None: "unverified"}[
            verdict
        ]
        if verdict is False:
            group["reason"] = (
                f"This server runs {pretty_name(dep_id)} {actual}, which is "
                f"outside the required range ({group['range_text']})."
            )

    @staticmethod
    def _judge_mod(
        group: dict[str, Any], present: dict[str, Any] | None, ranges: list[Range]
    ) -> None:
        """Another mod: missing, disabled, or installed at a matching version."""
        if present is None:
            group["status"] = "missing"
            return
        mod = present["mod"]
        group["installed_version"] = mod.version
        group["installed_filename"] = mod.filename
        if not present["enabled"]:
            group["status"] = "disabled"
            group["reason"] = f"{mod.name} is installed but turned off. Turn it on to use it."
            return
        verdict = combined_satisfies(mod.version, ranges)
        group["status"] = {True: "satisfied", False: "incompatible", None: "unverified"}[verdict]
        if verdict is False:
            group["reason"] = (
                f"{mod.name} {mod.version} is installed, but "
                f"{group['range_text']} is needed. It wasn't replaced "
                "automatically: update it or go back to another version."
            )

    def _report(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        missing_required = [
            g for g in items if g["status"] == "missing" and g["kind"] == "required"
        ]
        return {
            "items": items,
            "missing_required": [g["mod_id"] for g in missing_required],
            "counts": {
                status: len([g for g in items if g["status"] == status])
                for status in (
                    "missing",
                    "incompatible",
                    "disabled",
                    "unverified",
                    "platform_incompatible",
                    "satisfied",
                    "platform_ok",
                )
            },
            "minecraft_version": self.server.mc_version,
            "note": (
                "Only declared dependencies are checked. A mod can still need something "
                "it does not declare."
            ),
        }

    # ------------------------------------------------------------------ Modrinth lookups
    async def resolve_project(self, mod_id: str) -> dict[str, Any] | None:
        """Find the Modrinth project for a mod id. Cached; None if not found."""
        if not valid_identifier(mod_id):
            raise DependencyError(f"'{mod_id}' isn't a name a mod can have.")
        cache_key = f"dep_project:{mod_id}"
        cached = self.db.get_setting(cache_key)
        if cached and time.time() - cached.get("cached_at", 0) < CACHE_SECONDS:
            return cached.get("project")
        slug = modrinth_slug_for(mod_id)
        project = None
        try:
            info = await self.modrinth.project(slug)
            project = {
                "project_id": info["project_id"],
                "slug": info["slug"],
                "title": info["title"],
                "page": info["page"],
            }
        except ModrinthNotFound:
            try:
                found = await self.modrinth.search(mod_id, minecraft_version=None, limit=10)
            except ModrinthError:
                found = {"hits": []}
            wanted = re.sub(r"[^a-z0-9]", "", mod_id.lower())
            for hit in found.get("hits", []):
                if (
                    hit.get("slug") == mod_id
                    or re.sub(r"[^a-z0-9]", "", str(hit.get("title", "")).lower()) == wanted
                ):
                    project = {
                        "project_id": hit["project_id"],
                        "slug": hit["slug"],
                        "title": hit["title"],
                        "page": hit["page"],
                    }
                    break
        self.db.set_setting(cache_key, {"project": project, "cached_at": time.time()})
        return project

    async def describe(self, report: dict[str, Any]) -> dict[str, Any]:
        """Attach Modrinth names and links to items that need attention."""
        for item in report["items"]:
            if item["platform"] or item["status"] in ("satisfied",):
                continue
            try:
                project = await self.resolve_project(item["mod_id"])
            except (ModrinthError, DependencyError) as exc:
                item["modrinth"] = {"error": str(exc)}
                continue
            if project:
                item["modrinth"] = project
                item["name"] = project["title"]
            else:
                item["modrinth"] = {"not_found": True}
        return report

    # ------------------------------------------------------------------ planning
    async def _pick_version(
        self, slug: str, ranges: list[Range]
    ) -> tuple[dict | None, bool | None, str]:
        versions = await self.modrinth.versions(slug, self.server.mc_version)
        if not versions:
            mc = self.server.mc_version
            kind = self.manager.config.server_type.name
            return (
                None,
                None,
                (
                    f"There's no {kind} version of it for Minecraft {mc}."
                    if mc
                    else f"There's no {kind} version of it."
                ),
            )
        undecided = None
        for version in versions:
            verdict = combined_satisfies(version.get("version_number") or "", ranges)
            if verdict is True:
                return version, True, ""
            if verdict is None and undecided is None:
                undecided = version
        if undecided is not None:
            return undecided, None, "The needed version range couldn't be checked against this one."
        return (
            None,
            False,
            "No version on Modrinth fits "
            + " and ".join(describe_range(range_text(r)) for r in ranges)
            + ".",
        )

    async def plan(self, mod_ids: list[str] | None = None) -> dict[str, Any]:
        """Work out everything to download, including dependencies of
        dependencies, without downloading anything."""
        wanted = self._wanted(self.analyse(), mod_ids)
        installed = self._installed_index()
        queue: list[tuple[str, list[Range], list[str], int]] = [
            (
                mod_id,
                [(r["range"], r["syntax"]) for r in group["required_by"]],
                [r["name"] for r in group["required_by"]],
                0,
            )
            for mod_id, group in wanted.items()
        ]
        result: dict[str, Any] = {"planned": {}, "unresolvable": [], "skipped": []}
        while queue:
            queue.extend(await self._plan_step(*queue.pop(0), installed, result))

        items = sorted(result["planned"].values(), key=lambda i: -i["depth"])  # deepest first
        for item in items:
            item["range_text"] = (
                " and ".join(sorted({describe_range(range_text(r)) for r in item["ranges"]}))
                or "Any version"
            )
        return {
            "items": items,
            "unresolvable": result["unresolvable"],
            "skipped": result["skipped"],
            "minecraft_version": self.server.mc_version,
        }

    @staticmethod
    def _wanted(report: dict[str, Any], mod_ids: list[str] | None) -> dict[str, dict[str, Any]]:
        """The missing required dependencies to plan for, optionally a chosen few."""
        wanted = {
            g["mod_id"]: g
            for g in report["items"]
            if g["status"] == "missing" and g["kind"] == "required"
        }
        if mod_ids:
            for mod_id in mod_ids:
                if not valid_identifier(mod_id):
                    raise DependencyError(f"'{mod_id}' isn't a name a mod can have.")
            wanted = {k: v for k, v in wanted.items() if k in set(mod_ids)}
        return wanted

    async def _plan_step(
        self,
        mod_id: str,
        ranges: list[Range],
        chain: list[str],
        depth: int,
        installed: dict[str, Any],
        result: dict[str, Any],
    ) -> list[tuple]:
        """Plan one mod. Returns its own dependencies, to be planned next."""
        planned, unresolvable = result["planned"], result["unresolvable"]
        if depth > MAX_DEPTH:
            unresolvable.append({"mod_id": mod_id, "reason": "The dependency chain is too deep"})
            return []
        try:
            project = await self.resolve_project(mod_id)
        except DependencyError as exc:
            unresolvable.append({"mod_id": mod_id, "reason": str(exc)})
            return []
        if not project:
            unresolvable.append(
                {
                    "mod_id": mod_id,
                    "name": pretty_name(mod_id),
                    "required_by": chain,
                    "reason": "Not found on Modrinth. Install it manually.",
                }
            )
            return []
        key = project["slug"]
        if key in planned:
            planned[key]["ranges"].extend(ranges)
            planned[key]["required_by"] = sorted(set(planned[key]["required_by"] + chain))
            return []
        if key in installed or mod_id in installed:
            result["skipped"].append(
                {"mod_id": mod_id, "name": project["title"], "reason": "Already installed"}
            )
            return []
        version, verified, note = await self._pick_version(key, ranges)
        if version is None:
            unresolvable.append(
                {
                    "mod_id": mod_id,
                    "name": project["title"],
                    "required_by": chain,
                    "reason": note,
                    "page": project["page"],
                }
            )
            return []
        file_info = version.get("file") or {}
        planned[key] = {
            "mod_id": mod_id,
            "slug": key,
            "project_id": project["project_id"],
            "title": project["title"],
            "page": project["page"],
            "version_id": version["version_id"],
            "version_number": version["version_number"],
            "release_type": version.get("release_type"),
            "filename": file_info.get("filename"),
            "size": file_info.get("size"),
            "ranges": list(ranges),
            "range_verified": verified,
            "note": note,
            "required_by": sorted(set(chain)),
            "depth": depth,
        }
        return await self._required_by_version(version, project["title"], depth, unresolvable)

    async def _required_by_version(
        self, version: dict[str, Any], title: str, depth: int, unresolvable: list[dict[str, Any]]
    ) -> list[tuple]:
        """The required dependencies a Modrinth version declares, as queue entries."""
        found: list[tuple] = []
        for sub in version.get("dependencies", []):
            if sub.get("type") != "required" or not sub.get("project_id"):
                continue
            if not valid_identifier(sub["project_id"]):
                unresolvable.append(
                    {
                        "mod_id": str(sub["project_id"])[:40],
                        "reason": "Modrinth returned an invalid project id",
                    }
                )
                continue
            try:
                info = await self.modrinth.project(sub["project_id"])
            except ModrinthError as exc:
                unresolvable.append({"mod_id": sub["project_id"], "reason": str(exc)})
                continue
            found.append((info["slug"], [], [title], depth + 1))
        return found

    async def install(self, mod_ids: list[str] | None, user: str) -> dict[str, Any]:
        """Plan, then install each item through the normal verified path."""
        self.manager._require_server_offline("install dependencies")
        plan = await self.plan(mod_ids)
        results = []
        for item in plan["items"]:
            if item["slug"] in self._installed_index():  # installed earlier in this run
                results.append(
                    {"title": item["title"], "result": "skipped", "detail": "Already installed"}
                )
                continue
            log.info("dependency_detected mod=%s version=%s", item["slug"], item["version_number"])
            try:
                installed = await self.manager.install_from_modrinth(
                    item["slug"], user, version_id=item["version_id"], install_dependencies=False
                )
                results.append(
                    {
                        "title": item["title"],
                        "result": "installed",
                        "version": installed["installed"]["version"],
                    }
                )
                log.info("dependency_installed mod=%s", item["slug"])
            except Exception as exc:
                results.append({"title": item["title"], "result": "failed", "detail": str(exc)})
                log.warning("dependency_install_failed mod=%s reason=%s", item["slug"], exc)
        after = self.analyse()
        return {
            "plan": plan,
            "results": results,
            "still_missing": [
                g for g in after["items"] if g["status"] == "missing" and g["kind"] == "required"
            ],
        }
