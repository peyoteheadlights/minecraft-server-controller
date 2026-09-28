"""Java detection.

Source of truth: running the configured java executable with `-version` and
parsing its output. The version is never inferred from a path, a folder name,
or the Minecraft version. If parsing fails, `version_major` stays None and
every caller must treat that as unknown.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# "openjdk version "21.0.2" 2024-01-16"  /  "java version "1.8.0_391""
VERSION_RE = re.compile(r'version\s+"(?P<full>[^"]+)"')

# Minimum Java for each Minecraft generation, from Mojang's own requirements.
MINECRAFT_JAVA_REQUIREMENTS: list[tuple[tuple[int, ...], int]] = [
    ((1, 20, 5), 21),
    ((1, 18), 17),
    ((1, 17), 16),
    ((1, 12), 8),
]


@dataclass
class JavaInfo:
    requested: str = ""
    path: str | None = None
    executable_found: bool | None = None
    version_string: str | None = None
    version_major: int | None = None
    vendor: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "path": self.path,
            "executable_found": self.executable_found,
            "version_string": self.version_string,
            "version_major": self.version_major,
            "vendor": self.vendor,
            "error": self.error,
        }


def detect_java(java: str = "java", timeout: float = 20.0) -> JavaInfo:
    info = JavaInfo(requested=java)
    candidate = Path(java)
    resolved = str(candidate) if candidate.is_file() else shutil.which(java)
    if not resolved:
        info.executable_found = False
        info.error = f"The java executable was not found: {java}"
        return info
    info.executable_found = True
    info.path = resolved
    try:
        from ..winproc import NO_WINDOW
        proc = subprocess.run([resolved, "-version"], capture_output=True, text=True,
                              timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        info.error = f"java -version could not be run: {exc}"
        return info
    output = ((proc.stderr or "") + (proc.stdout or "")).strip()
    if not output:
        info.error = "java -version produced no output, so the version is unknown"
        return info
    first = output.splitlines()[0].strip()
    info.version_string = first
    if "openjdk" in first.lower():
        info.vendor = "OpenJDK"
    elif "java" in first.lower():
        info.vendor = "Oracle Java"
    match = VERSION_RE.search(output)
    if not match:
        info.error = "The java -version output could not be parsed, so the version is unknown"
        return info
    full = match.group("full")
    parts = full.split(".")
    try:
        first_part = int(parts[0])
        # Java 8 and older report as 1.8.0_x
        info.version_major = int(parts[1]) if first_part == 1 and len(parts) > 1 else first_part
    except (ValueError, IndexError):
        info.error = f"The Java version string '{full}' could not be interpreted"
    return info


def _parse_minecraft(version: str) -> tuple[int, ...] | None:
    cleaned = re.match(r"^(\d+(?:\.\d+)*)", str(version or "").strip())
    if not cleaned:
        return None
    try:
        return tuple(int(p) for p in cleaned.group(1).split("."))
    except ValueError:
        return None


def required_java(minecraft_version: str | None) -> int | None:
    """Minimum Java major version for a Minecraft version, or None if the
    Minecraft version is unknown or unrecognised."""
    parsed = _parse_minecraft(minecraft_version) if minecraft_version else None
    if not parsed:
        return None
    for threshold, java_major in MINECRAFT_JAVA_REQUIREMENTS:
        if parsed >= threshold:
            return java_major
    return 8


def check_compatibility(java: JavaInfo, minecraft_version: str | None) -> dict[str, Any]:
    """Compare detected Java against the Minecraft version.

    Returns one of four verdicts and never claims more than it knows:
      compatible    - both versions known and the requirement is met
      incompatible  - both known and the requirement is not met
      unknown       - Java version or Minecraft version could not be determined
    """
    needed = required_java(minecraft_version)
    if java.version_major is None:
        return {
            "verdict": "unknown",
            "detail": java.error or "The installed Java version could not be detected",
            "java_major": None, "required": needed, "minecraft_version": minecraft_version,
        }
    if needed is None:
        return {
            "verdict": "unknown",
            "detail": ("The Minecraft version is not known yet, so the Java requirement cannot be "
                       "checked. It is detected from the server console on first start."),
            "java_major": java.version_major, "required": None,
            "minecraft_version": minecraft_version,
        }
    if java.version_major >= needed:
        return {
            "verdict": "compatible",
            "detail": f"Minecraft {minecraft_version} needs Java {needed}; Java {java.version_major} is installed",
            "java_major": java.version_major, "required": needed,
            "minecraft_version": minecraft_version,
        }
    return {
        "verdict": "incompatible",
        "detail": (f"Minecraft {minecraft_version} needs Java {needed} or newer, but Java "
                   f"{java.version_major} is installed. Install the right JDK, or point "
                   f"server.java at it."),
        "java_major": java.version_major, "required": needed,
        "minecraft_version": minecraft_version,
    }
