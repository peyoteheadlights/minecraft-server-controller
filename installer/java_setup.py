"""Java, handled for the person running the installer.

The installer finds the Java programs already on the PC and checks each
one's real version by running it. If none is new enough for Minecraft, it
offers Eclipse Temurin (Adoptium's official Java):

1. ask Adoptium's API which Temurin release is current for that version,
2. download the Windows installer (MSI) from the link Adoptium gives, only
   from Adoptium's own hosts over HTTPS, through the app's safe downloader,
3. check it against the SHA-256 Adoptium publishes (a mismatch throws the
   file away and nothing is installed),
4. install it with Windows Installer (msiexec, an argument list, no shell),
5. check the new java.exe really runs and reports that version, and point
   the servers at it.

This runs only in the installer, on the PC, with the person there. The
dashboard never installs Java; it points to the installer instead.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent import downloads
from agent.minecraft.java import MINECRAFT_JAVA_REQUIREMENTS, detect_java

ADOPTIUM_API = "https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
# Long-term-support versions Temurin publishes that Minecraft uses.
LTS = (17, 21, 25)
NEWEST_NEEDED = max(java for _, java in MINECRAFT_JAVA_REQUIREMENTS)


class JavaSetupError(RuntimeError):
    pass


@dataclass
class JavaFound:
    path: str
    major: int | None
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "major": self.major, "version": self.version}


def candidate_paths() -> list[Path]:
    """Places Java usually is on Windows, plus PATH and JAVA_HOME."""
    out: list[Path] = []
    on_path = shutil.which("java")
    if on_path:
        out.append(Path(on_path))
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        out.append(Path(java_home) / "bin" / "java.exe")
    for base in {os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\Program Files"}:
        for vendor in ("Eclipse Adoptium", "Java", "Microsoft", "Zulu", "Amazon Corretto"):
            folder = Path(base) / vendor
            if folder.is_dir():
                out.extend(sorted(folder.glob("*/bin/java.exe"), reverse=True))
    seen, unique = set(), []
    for path in out:
        key = os.path.normcase(str(path))
        if key not in seen and path.is_file():
            seen.add(key)
            unique.append(path)
    return unique


def find_java(paths: list[Path] | None = None) -> list[JavaFound]:
    """Every Java found, newest first, each version read by running it."""
    found = []
    for path in paths if paths is not None else candidate_paths():
        info = detect_java(str(path))
        found.append(JavaFound(str(path), info.version_major, info.version_string))
    return sorted(found, key=lambda j: j.major or 0, reverse=True)


def best_java(found: list[JavaFound], needed: int = NEWEST_NEEDED) -> JavaFound | None:
    """The newest Java that is new enough, or None."""
    for java in found:
        if java.major is not None and java.major >= needed:
            return java
    return None


def temurin_major(needed: int) -> int:
    """The Temurin long-term-support version to install for ``needed``."""
    for major in LTS:
        if major >= needed:
            return major
    return LTS[-1]


async def _latest_release(major: int) -> dict[str, Any]:
    url = (
        ADOPTIUM_API.format(major=major)
        + "?architecture=x64&image_type=jre&os=windows&vendor=eclipse"
    )
    answer = await downloads.fetch_json(url)
    if not isinstance(answer, list) or not answer:
        raise JavaSetupError(f"Adoptium didn't list a Java {major} for Windows.")
    release = answer[0]
    installer = (release.get("binary") or {}).get("installer") or {}
    if not installer.get("link") or not installer.get("checksum"):
        raise JavaSetupError(
            f"Adoptium's Java {major} has no Windows installer with a checksum, so it wasn't used."
        )
    return {
        "link": installer["link"],
        "sha256": str(installer["checksum"]).lower(),
        "size": installer.get("size"),
        "name": installer.get("name") or f"temurin-{major}.msi",
        "version": (release.get("version") or {}).get("semver")
        or release.get("release_name")
        or str(major),
    }


def download_temurin(
    major: int, folder: Path, report: Callable[[int, int | None], None] | None = None
) -> dict[str, Any]:
    """Download and check Temurin's MSI. Returns where it is and its version."""

    async def go() -> dict[str, Any]:
        release = await _latest_release(major)
        spec = downloads.FileSpec(
            url=release["link"],
            name=f"temurin-{major}-jre.msi",
            sha256=release["sha256"],
            size=int(release["size"]) if release.get("size") else None,
            allow_unverified=False,
        )
        fetched = await downloads.download(spec, folder, report=report)
        return {**release, "path": str(fetched.path), "verified": fetched.verified}

    return asyncio.run(go())


def install_command(msi: Path, log_file: Path) -> list[str]:
    """Windows Installer, quietly, with only Java itself (no file
    associations), logged. An argument list: no shell is involved."""
    return [
        "msiexec.exe",
        "/i",
        str(msi),
        "/qn",
        "/norestart",
        "ADDLOCAL=FeatureMain",
        "/l*v",
        str(log_file),
    ]


def installed_java(major: int) -> JavaFound | None:
    """Temurin's java.exe for ``major`` after installing, checked by running it."""
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eclipse Adoptium"
    paths = sorted(base.glob(f"jre-{major}*/bin/java.exe"), reverse=True)
    found = best_java(find_java(paths), major)
    return found
