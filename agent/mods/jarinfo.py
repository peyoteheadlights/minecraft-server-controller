"""Reading mod and plugin metadata out of a .jar.

Each loader keeps its metadata in its own file inside the jar:

    fabric.mod.json                  Fabric
    quilt.mod.json                   Quilt
    META-INF/mods.toml               Forge (and NeoForge before 1.20.5)
    META-INF/neoforge.mods.toml      NeoForge
    plugin.yml / paper-plugin.yml    Bukkit, Spigot and Paper plugins

We read it without executing anything: the jar is opened as a zip, the
metadata members are parsed as JSON, TOML or YAML, and the file is closed.
Nothing is ever loaded into a JVM by this agent. One jar can carry several
of these files (a mod built for more than one loader); every loader found
is recorded in ``loaders``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tomllib
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
    # How version_range is written: "fabric" (">=1.2 <2"), "maven"
    # ("[1.2,2)", Forge and NeoForge) or "unknown" (not checked).
    syntax: str = "fabric"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mod_id": self.mod_id,
            "version_range": self.version_range,
            "kind": self.kind,
            "syntax": self.syntax,
        }


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
    # The first loader found: fabric | quilt | forge | neoforge | paper |
    # bukkit | unknown. ``loaders`` has every one the jar declares.
    loader: str = "fabric"
    loaders: list[str] = field(default_factory=list)
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
            "loaders": self.loaders or [self.loader],
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


LOADER_NAMES = {
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "paper": "Paper",
    "bukkit": "Bukkit/Spigot",
    "unknown": "an unknown loader",
}


def _read_fabric(info: ModInfo, data: dict) -> None:
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


def _quilt_range(value: Any) -> tuple[str, str]:
    """(range, syntax) from a quilt.mod.json "versions" value."""
    if value is None:
        return "*", "fabric"
    if isinstance(value, str):
        return value, "fabric"
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return " || ".join(value), "fabric"
    return json.dumps(value), "unknown"  # {"any": ...} / {"all": ...}: not checked


def _read_quilt(info: ModInfo, data: dict) -> None:
    block = data.get("quilt_loader") or {}
    meta = block.get("metadata") or {}
    info.mod_id = str(block.get("id", "") or "")
    info.version = str(block.get("version", "") or "")
    info.name = str(meta.get("name", "") or info.mod_id)
    info.description = str(meta.get("description", "") or "")[:500]
    contributors = meta.get("contributors") or {}
    if isinstance(contributors, dict):
        info.authors = [str(name) for name in contributors]
    for kind, key in (("depends", "depends"), ("breaks", "breaks")):
        for entry in block.get(key) or []:
            if isinstance(entry, str):
                dep = ModDependency(entry, "*", kind)
            elif isinstance(entry, dict) and entry.get("id"):
                spec, syntax = _quilt_range(entry.get("versions"))
                optional = bool(entry.get("optional"))
                dep_kind = "recommends" if kind == "depends" and optional else kind
                dep = ModDependency(str(entry["id"]), spec, dep_kind, syntax)
            else:
                continue
            (info.breaks if kind == "breaks" else info.dependencies).append(dep)
    for dep in info.dependencies:
        if dep.mod_id == "minecraft":
            info.minecraft_range = dep.version_range


def _manifest_version(zf: zipfile.ZipFile) -> str:
    try:
        text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    except KeyError:
        return ""
    for line in text.splitlines():
        if line.startswith("Implementation-Version:"):
            return line.split(":", 1)[1].strip()
    return ""


def _read_forge_toml(info: ModInfo, zf: zipfile.ZipFile, member: str) -> None:
    data = tomllib.loads(zf.read(member).decode("utf-8", errors="replace"))
    mods = data.get("mods") or []
    first = mods[0] if mods and isinstance(mods[0], dict) else {}
    info.mod_id = str(first.get("modId", "") or "")
    version = str(first.get("version", "") or "")
    if "${" in version:  # "${file.jarVersion}": the version is in the manifest
        version = _manifest_version(zf)
    info.version = version
    info.name = str(first.get("displayName", "") or info.mod_id)
    info.description = str(first.get("description", "") or "").strip()[:500]
    info.authors = _as_list(first.get("authors"))
    dependencies = data.get("dependencies") or {}
    entries = dependencies.get(info.mod_id) if isinstance(dependencies, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("modId"):
            continue
        kind_word = str(entry.get("type", "") or "").lower()
        if not kind_word:  # older files: mandatory = true/false
            kind_word = "required" if entry.get("mandatory", True) else "optional"
        kind = {
            "required": "depends",
            "optional": "recommends",
            "incompatible": "breaks",
            "discouraged": "conflicts",
        }.get(kind_word, "recommends")
        side = str(entry.get("side", "BOTH")).upper()
        if side == "CLIENT":
            continue  # only matters on players' computers
        dep = ModDependency(
            str(entry["modId"]), str(entry.get("versionRange", "") or "*"), kind, "maven"
        )
        (info.breaks if kind in ("breaks", "conflicts") else info.dependencies).append(dep)
    for dep in info.dependencies:
        if dep.mod_id == "minecraft":
            info.minecraft_range = dep.version_range


def _read_plugin_yml(info: ModInfo, zf: zipfile.ZipFile, member: str) -> None:
    import yaml

    data = yaml.safe_load(zf.read(member).decode("utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{member} isn't laid out the way that file should be.")
    info.mod_id = str(data.get("name", "") or "")
    info.name = info.mod_id
    info.version = str(data.get("version", "") or "")
    info.description = str(data.get("description", "") or "")[:500]
    info.authors = _as_list(data.get("authors")) or _as_list(data.get("author"))
    api = str(data.get("api-version", "") or "").strip()
    if api:
        # The oldest Minecraft API the plugin was built for. Paper refuses
        # to load a plugin built for a newer API than the server's.
        info.minecraft_range = f">={api}"
        info.dependencies.append(ModDependency("minecraft", f">={api}", "depends"))
    if member == "paper-plugin.yml":
        server = ((data.get("dependencies") or {}).get("server")) or {}
        if isinstance(server, dict):
            for name, spec in server.items():
                required = not isinstance(spec, dict) or spec.get("required", True)
                kind = "depends" if required else "recommends"
                info.dependencies.append(ModDependency(str(name), "*", kind))
    else:
        for name in _as_list(data.get("depend")):
            info.dependencies.append(ModDependency(name, "*", "depends"))
        for name in _as_list(data.get("softdepend")):
            info.dependencies.append(ModDependency(name, "*", "recommends"))


def read_mod_jar(path: Path, compute_hash: bool = True) -> ModInfo:
    """Read mod or plugin metadata from a jar. Never raises for a bad jar."""
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
    member = ""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            found = [
                (loader, name)
                for loader, name in (
                    ("fabric", "fabric.mod.json"),
                    ("quilt", "quilt.mod.json"),
                    ("neoforge", "META-INF/neoforge.mods.toml"),
                    ("forge", "META-INF/mods.toml"),
                    ("paper", "paper-plugin.yml"),
                    ("bukkit", "plugin.yml"),
                )
                if name in names
            ]
            if not found and "mcmod.info" in names:
                found = [("forge", "mcmod.info")]  # Forge before 1.13
            info.loaders = [loader for loader, _ in found]
            if not found:
                info.loader = "unknown"
                info.loaders = ["unknown"]
                info.problems.append(
                    "No mod or plugin information was found inside this file, so it may "
                    "not be a mod or plugin."
                )
            else:
                if ("forge", "META-INF/mods.toml") in found and "neoforge" not in info.loaders:
                    # NeoForge for Minecraft 1.20.1 to 1.20.4 still used
                    # mods.toml; such a mod says so by depending on neoforge.
                    if _depends_on_neoforge(zf):
                        info.loaders = [
                            "neoforge" if loader == "forge" else loader for loader in info.loaders
                        ]
                        found = [
                            ("neoforge", name) if loader == "forge" else (loader, name)
                            for loader, name in found
                        ]
                info.loader, member = found[0]
                if member == "fabric.mod.json":
                    _read_fabric(info, json.loads(_text(zf, member), strict=False))
                elif member == "quilt.mod.json":
                    _read_quilt(info, json.loads(_text(zf, member), strict=False))
                elif member.endswith(".toml"):
                    _read_forge_toml(info, zf, member)
                elif member.endswith(".yml"):
                    _read_plugin_yml(info, zf, member)
    except zipfile.BadZipFile:
        info.loader = "unknown"
        info.loaders = ["unknown"]
        info.problems.append("This file isn't a readable .jar file.")
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        log.info("could not read %s in %s: %s", member, filename, exc)
        info.problems.append(_unreadable(member))
    except Exception as exc:  # a broken YAML file, an odd encoding
        log.info("could not read %s in %s: %s", member, filename, exc)
        info.problems.append(_unreadable(member))

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


def _unreadable(member: str) -> str:
    what = "plugin" if member.endswith(".yml") else "mod"
    return (
        f"The {what}'s own description inside the file ({member or 'none found'}) is damaged, "
        "so its name, version and needs can't be shown."
    )


def _depends_on_neoforge(zf: zipfile.ZipFile) -> bool:
    try:
        data = tomllib.loads(zf.read("META-INF/mods.toml").decode("utf-8", errors="replace"))
    except (KeyError, tomllib.TOMLDecodeError):
        return False
    dependencies = data.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        return False
    return any(
        isinstance(entry, dict) and str(entry.get("modId", "")).lower() == "neoforge"
        for entries in dependencies.values()
        if isinstance(entries, list)
        for entry in entries
    )


def _text(zf: zipfile.ZipFile, member: str) -> str:
    # Some mods ship their metadata with control characters; strict=False
    # in json.loads accepts them.
    return zf.read(member).decode("utf-8", errors="replace")


def wrong_loader_reason(info: ModInfo, accepts: tuple[str, ...], type_name: str) -> str | None:
    """Why this jar won't load on a server that accepts ``accepts``, in
    plain words, or None when it fits."""
    loaders = info.loaders or [info.loader]
    if any(loader in accepts for loader in loaders):
        return None
    if loaders == ["unknown"]:
        return (
            f"{info.filename} has no mod or plugin information inside, so a {type_name} "
            "server can't use it."
        )
    built_for = " and ".join(LOADER_NAMES.get(loader, loader) for loader in loaders)
    return f"{info.name or info.filename} is made for {built_for}, so it won't work on a {type_name} server."


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


def range_satisfies(version: str, spec: str, syntax: str = "fabric") -> bool | None:
    """Check ``version`` against a range written in ``syntax``. None means
    the range could not be checked."""
    if syntax == "maven":
        return maven_satisfies(version, spec)
    if syntax == "unknown":
        return None
    return version_satisfies(version, spec)


MAVEN_RANGE_RE = re.compile(r"([\[(])\s*([^,\])]*)\s*(?:,\s*([^\])]*))?\s*([\])])")


def maven_satisfies(version: str, spec: str) -> bool | None:
    """Does ``version`` fall in the Maven range ``spec`` (Forge and NeoForge
    write their ranges this way)?

        [1.20.1,1.21)   1.20.1 up to, not including, 1.21
        [47,)           47 or newer
        [1.20.1]        exactly 1.20.1
        1.20.1          any version (Maven reads a bare version as a
                        preference, not a requirement)
    """
    spec = str(spec or "").strip()
    if not spec or spec in ("*", "any"):
        return True
    if not version:
        return None
    if not any(ch in spec for ch in "[("):
        return True
    matches = list(MAVEN_RANGE_RE.finditer(spec))
    if not matches:
        return None
    for match in matches:
        opening, low, high, closing = match.groups()
        low = (low or "").strip()
        if high is None:  # [x] exact
            if _cmp(version, low) == 0:
                return True
            continue
        high = high.strip()
        ok = True
        if low:
            result = _cmp(version, low)
            ok = result > 0 or (result == 0 and opening == "[")
        if ok and high:
            result = _cmp(version, high)
            ok = result < 0 or (result == 0 and closing == "]")
        if ok:
            return True
    return False


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
            target = clause[len(op) :].strip()
            if not target:
                return None
            result = _cmp(version, target)
            return {
                ">=": result >= 0,
                "<=": result <= 0,
                ">": result > 0,
                "<": result < 0,
                "=": result == 0,
                "!=": result != 0,
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
