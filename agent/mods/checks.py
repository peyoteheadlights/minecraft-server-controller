"""The individual checks behind ModManager.check_all.

Each function looks at one thing a mod declares and returns the issues it
found. They read declared metadata only; nothing is executed.
"""

from __future__ import annotations

from typing import Any

from .dependencies import describe_range, pretty_name
from .jarinfo import ModInfo, version_satisfies

Issue = dict[str, Any]

# Dependencies on the platform rather than on another mod.
PLATFORM_IDS = ("minecraft", "java", "fabricloader", "fabric-loader")


def duplicate_ids(enabled: list[ModInfo]) -> list[Issue]:
    """Two enabled jars that provide the same mod id."""
    seen: dict[str, list[str]] = {}
    for mod in enabled:
        seen.setdefault(mod.mod_id, []).append(mod.filename)
    return [{
        "kind": "duplicate_mod_id",
        "severity": "error",
        "mod_id": mod_id,
        "detail": f"{mod_id} is provided by {len(files)} enabled jars: {', '.join(files)}",
    } for mod_id, files in seen.items() if len(files) > 1]


def jar_issues(mod: ModInfo) -> list[Issue]:
    """Problems reading the jar, and mods built for another loader."""
    issues = [{"kind": "jar", "severity": "warn", "detail": p} for p in mod.problems]
    if mod.loader == "forge":
        issues.append({"kind": "loader_mismatch", "severity": "error",
                       "detail": "Forge mod on a Fabric server. It will not load."})
    return issues


def platform_dependency_issue(mod: ModInfo, dep, mc_version: str | None,
                              loader_version: str | None) -> Issue | None:
    """A required Minecraft, Java or Fabric Loader version."""
    target = {"minecraft": mc_version, "java": None,
              "fabricloader": loader_version, "fabric-loader": loader_version}[dep.mod_id]
    if not target:
        return None  # not known yet, so nothing to compare against
    ok = version_satisfies(target, dep.version_range)
    if ok is False:
        return {"kind": "version_mismatch", "severity": "error",
                "detail": f"{mod.name} needs {dep.mod_id} {dep.version_range}, "
                          f"this server runs {target}"}
    if ok is None:
        return {"kind": "unverified", "severity": "info",
                "detail": f"Could not check {dep.mod_id} range '{dep.version_range}' "
                          f"against {target}"}
    return None


def mod_dependency_issue(mod: ModInfo, dep, installed: dict[str, ModInfo]) -> Issue | None:
    """A required mod that is missing, disabled or the wrong version."""
    provider = installed.get(dep.mod_id)
    if provider is None:
        # Fabric API ships many sub-modules under fabric-api
        if dep.mod_id.startswith("fabric-") and "fabric-api" in installed:
            return None
        return {"kind": "missing_dependency", "severity": "error",
                "mod_id": dep.mod_id, "required": dep.version_range,
                "detail": f"{mod.name} needs {pretty_name(dep.mod_id)} "
                          f"({describe_range(dep.version_range)}), which is not installed "
                          f"or is disabled"}
    ok = version_satisfies(provider.version, dep.version_range)
    if ok is False:
        return {"kind": "dependency_version", "severity": "error",
                "mod_id": dep.mod_id, "required": dep.version_range,
                "installed": provider.version,
                "detail": f"{mod.name} needs {pretty_name(dep.mod_id)} "
                          f"{describe_range(dep.version_range)}, but "
                          f"{provider.version} is installed"}
    if ok is None:
        return {"kind": "unverified", "severity": "info",
                "detail": f"Could not check '{dep.version_range}' for {dep.mod_id} "
                          f"against installed {provider.version}"}
    return None


def dependency_issues(mod: ModInfo, installed: dict[str, ModInfo],
                      mc_version: str | None, loader_version: str | None) -> list[Issue]:
    issues = []
    for dep in mod.dependencies:
        if dep.kind != "depends":
            continue
        if dep.mod_id in PLATFORM_IDS:
            issue = platform_dependency_issue(mod, dep, mc_version, loader_version)
        else:
            issue = mod_dependency_issue(mod, dep, installed)
        if issue:
            issues.append(issue)
    return issues


def breaks_issues(mod: ModInfo, installed: dict[str, ModInfo]) -> list[Issue]:
    """Installed mods this mod declares it is incompatible with."""
    issues = []
    for bad in mod.breaks:
        provider = installed.get(bad.mod_id)
        if provider is None:
            continue
        if version_satisfies(provider.version, bad.version_range) is not False:
            issues.append({
                "kind": "known_incompatibility", "severity": "error",
                "mod_id": bad.mod_id,
                "detail": f"{mod.name} declares it breaks with {bad.mod_id} "
                          f"{bad.version_range} (installed: {provider.version})",
            })
    return issues


def status_of(issues: list[Issue]) -> str:
    if any(i["severity"] == "error" for i in issues):
        return "error"
    if any(i["severity"] == "warn" for i in issues):
        return "warn"
    return "ok"
