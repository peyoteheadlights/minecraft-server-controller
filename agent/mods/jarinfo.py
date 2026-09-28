"""Reading Fabric metadata out of a .jar.

A Fabric mod jar contains fabric.mod.json at its root. We read it without
executing anything: the jar is opened as a zip, one member is parsed as JSON,
and the file is closed. Nothing is ever loaded into a JVM by this agent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("msc.mods.jar")

DISABLED_SUFFIX = ".disabled"
# Fabric ignores anything that is not exactly *.jar, so "x.jar.disabled" is
# not loaded. We still keep disabled files in the same folder for clarity.

SEMVER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[.\-+](.*))?$")


@dataclass
class ModDependency:
    mod_id: str
    version_range: str
    kind: str = "depends"  # depends | recommends | suggests | breaks | conflicts

    def to_dict(self) -> dict[str, Any]:
        return {"mod_id": self.mod_id, "version_range": self.version_range, "kind": self.kind}


@dataclass
class ModInfo:
    filename: str
    path: str
    mod_id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    authors: list[str] = field(default_factory=list)
    environment: str = "*"
    enabled: bool = True
    size_bytes: int = 0
    modified: float = 0.0
    loader: str = "fabric"        # fabric | forge | quilt | unknown
    dependencies: list[ModDependency] = field(default_factory=list)
    breaks: list[ModDependency] = field(default_factory=list)
    minecraft_range: str = ""
    sha256: str = ""
    problems: list[str] = field(default_factory=list)
    modrinth_project: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "path": self.path,
            "mod_id": self.mod_id,
            "name": self.name or self.mod_id or self.filename,
            "version": self.version,
            "description": self.description,
            "authors": self.authors,
            "environment": self.environment,
            "enabled": self.enabled,
            "size_bytes": self.size_bytes,
            "modified": self.modified,
            "loader": self.loader,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "breaks": [d.to_dict() for d in self.breaks],
            "minecraft_range": self.minecraft_range,
            "sha256": self.sha256,
            "problems": self.problems,
            "modrinth_project": self.modrinth_project,
        }


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def sha512_bytes(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and "name" in item:
                out.append(str(item["name"]))
        return out
    return []


def _deps(block: dict | None, kind: str) -> list[ModDependency]:
    out: list[ModDependency] = []
    for mod_id, spec in (block or {}).items():
        if isinstance(spec, list):
            spec = " || ".join(str(s) for s in spec)
        out.append(ModDependency(mod_id=str(mod_id), version_range=str(spec), kind=kind))
    return out


def read_mod_jar(path: Path, compute_hash: bool = True) -> ModInfo:
    """Read Fabric metadata from a jar. Never raises for a bad jar."""
    path = Path(path)
    filename = path.name
    enabled = not filename.endswith(DISABLED_SUFFIX)
    stat = path.stat()
    info = ModInfo(
        filename=filename,
        path=str(path),
        enabled=enabled,
        size_bytes=stat.st_size,
        modified=stat.st_mtime,
    )
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "fabric.mod.json" in names:
                raw = zf.read("fabric.mod.json").decode("utf-8", errors="replace")
                # some mods ship fabric.mod.json with control characters
                data = json.loads(raw, strict=False)
                info.loader = "fabric"
                info.mod_id = str(data.get("id", "") or "")
                info.name = str(data.get("name", "") or info.mod_id)
                info.version = str(data.get("version", "") or "")
                info.description = str(data.get("description", "") or "")[:500]
                info.authors = _as_list(data.get("authors"))
                info.environment = str(data.get("environment", "*"))
                info.dependencies = _deps(data.get("depends"), "depends")
                info.dependencies += _deps(data.get("recommends"), "recommends")
                info.breaks = _deps(data.get("breaks"), "breaks")
                info.breaks += _deps(data.get("conflicts"), "conflicts")
                for dep in info.dependencies:
                    if dep.mod_id == "minecraft":
                        info.minecraft_range = dep.version_range
                contact = data.get("contact") or {}
                if isinstance(contact, dict):
                    for key in ("sources", "homepage", "issues"):
                        url = str(contact.get(key, ""))
                        if "modrinth.com" in url:
                            info.modrinth_project = url.rstrip("/").split("/")[-1]
                            break
            elif "quilt.mod.json" in names:
                info.loader = "quilt"
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8", errors="replace"), strict=False)
                loader_block = (data.get("quilt_loader") or {})
                info.mod_id = str(loader_block.get("id", ""))
                info.version = str(loader_block.get("version", ""))
                info.name = str((loader_block.get("metadata") or {}).get("name", info.mod_id))
                info.problems.append("This is a Quilt mod. Fabric may or may not load it.")
            elif "META-INF/mods.toml" in names or "mcmod.info" in names:
                info.loader = "forge"
                info.problems.append("This looks like a Forge mod. A Fabric server cannot load it.")
            else:
                info.loader = "unknown"
                info.problems.append("No fabric.mod.json found. This may not be a Fabric mod.")
    except zipfile.BadZipFile:
        info.loader = "unknown"
        info.problems.append("The file is not a readable jar archive.")
    except json.JSONDecodeError as exc:
        info.problems.append(f"fabric.mod.json could not be parsed: {exc}")
    except OSError as exc:  # pragma: no cover
        info.problems.append(f"The file could not be read: {exc}")

    if not info.mod_id:
        stem = filename[: -len(DISABLED_SUFFIX)] if not enabled else filename
        info.mod_id = Path(stem).stem.lower()
        info.name = info.name or Path(stem).stem
    if compute_hash:
        try:
            info.sha256 = sha256_file(path)
        except OSError:  # pragma: no cover
            pass
    return info


# ----------------------------------------------------------------------
# Version range checking (a pragmatic subset of the Fabric spec)
# ----------------------------------------------------------------------
def parse_version(version: str) -> tuple[int, int, int, str]:
    cleaned = str(version).strip().lstrip("vV")
    cleaned = cleaned.split("+")[0]
    m = SEMVER_RE.match(cleaned)
    if not m:
        return (0, 0, 0, cleaned)
    major = int(m.group(1) or 0)
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return (major, minor, patch, m.group(4) or "")


def _cmp(a: str, b: str) -> int:
    va, vb = parse_version(a)[:3], parse_version(b)[:3]
    return (va > vb) - (va < vb)


def version_satisfies(version: str, spec: str) -> bool | None:
    """Does `version` satisfy the Fabric range `spec`?

    Returns True/False, or None when the range uses syntax this checker does
    not model - in which case callers must report 'could not be verified'
    instead of pretending the check passed.
    """
    if not spec or spec in ("*", "any"):
        return True
    if not version:
        return None
    for clause in str(spec).split("||"):
        clause = clause.strip()
        if not clause:
            continue
        if _clause_ok(version, clause):
            return True
    # every clause failed, but if any clause was unparseable say "unknown"
    if any(_clause_ok(version, c.strip()) is None for c in str(spec).split("||")):
        return None
    return False


def _clause_ok(version: str, clause: str) -> bool | None:
    clause = clause.strip()
    if not clause or clause == "*":
        return True
    for op in (">=", "<=", "!=", ">", "<", "="):
        if clause.startswith(op):
            target = clause[len(op):].strip()
            if not target:
                return None
            result = _cmp(version, target)
            return {
                ">=": result >= 0, "<=": result <= 0, ">": result > 0,
                "<": result < 0, "=": result == 0, "!=": result != 0,
            }[op]
    if clause.startswith("~"):  # ~1.2.3 -> >=1.2.3 <1.3.0
        target = clause[1:].strip()
        major, minor, _, _ = parse_version(target)
        return _cmp(version, target) >= 0 and parse_version(version)[:2] == (major, minor)
    if clause.startswith("^"):  # ^1.2.3 -> >=1.2.3 <2.0.0
        target = clause[1:].strip()
        major = parse_version(target)[0]
        return _cmp(version, target) >= 0 and parse_version(version)[0] == major
    if clause.endswith(".x") or clause.endswith(".*"):
        prefix = clause[:-2]
        return str(version).startswith(prefix)
    if any(ch in clause for ch in "[]()"):
        return None  # Maven-style ranges: not modelled, report unknown
    return _cmp(version, clause) == 0
