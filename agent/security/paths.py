"""Filesystem safety helpers.

Every path that comes from an API request, a Modrinth response or a filename
inside an archive goes through here. The rules:

  * a caller-supplied name is a single path component, nothing else
  * only an explicit extension allow-list is accepted
  * resolved paths must stay inside a declared base directory
  * symlinks and Windows reparse points are refused, never followed
"""

from __future__ import annotations

import os
import re
import stat as stat_module
from pathlib import Path

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-() ]{0,190}$")
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
EXECUTABLE_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".scr", ".com", ".vbs",
    ".js", ".jse", ".wsf", ".wsh", ".dll", ".lnk", ".reg", ".py", ".jsp",
}


class PathSafetyError(ValueError):
    """Raised when a path or filename fails a safety rule."""


def safe_filename(name: str, allowed_extensions: set[str] | None = None) -> str:
    """Validate a single filename. Returns it unchanged, or raises."""
    if not name or name in (".", ".."):
        raise PathSafetyError("Empty or relative filename")
    if "/" in name or "\\" in name or "\0" in name:
        raise PathSafetyError(f"A filename must not contain a path: {name!r}")
    if name != name.strip() or name.endswith("."):
        raise PathSafetyError(f"Filename has stray whitespace or a trailing dot: {name!r}")
    if not SAFE_NAME_RE.match(name):
        raise PathSafetyError(f"Filename contains characters that are not allowed: {name!r}")
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        raise PathSafetyError(f"{name!r} is a reserved Windows device name")
    suffix = Path(name).suffix.lower()
    if suffix in EXECUTABLE_EXTENSIONS:
        raise PathSafetyError(f"{suffix} files are never downloaded or written by this agent")
    if allowed_extensions is not None and suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise PathSafetyError(f"Only {allowed} files are allowed here, got {suffix or 'no extension'}")
    return name


def is_inside(base: Path, target: Path) -> bool:
    try:
        base_resolved = Path(base).resolve()
        target_resolved = Path(target).resolve()
    except OSError:  # pragma: no cover
        return False
    return base_resolved == target_resolved or base_resolved in target_resolved.parents


def safe_join(base: Path, *parts: str, allowed_extensions: set[str] | None = None) -> Path:
    """Join caller-supplied components onto base and verify containment."""
    base = Path(base)
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        safe_filename(part, allowed_extensions if last else None)
    candidate = base.joinpath(*parts)
    if not is_inside(base, candidate):
        raise PathSafetyError("The resolved path escapes its base directory")
    return candidate


def assert_not_symlink(path: Path) -> Path:
    p = Path(path)
    if p.is_symlink():
        raise PathSafetyError(f"{p} is a symbolic link; refusing to follow it")
    if os.name == "nt" and p.exists():
        try:
            attrs = os.stat(p, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            if attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PathSafetyError(f"{p} is a reparse point; refusing to follow it")
        except (AttributeError, OSError):  # pragma: no cover
            pass
    return p


def safe_existing(base: Path, name: str, allowed_extensions: set[str] | None = None) -> Path:
    target = safe_join(base, name, allowed_extensions=allowed_extensions)
    if not target.exists():
        raise PathSafetyError(f"{name} was not found")
    assert_not_symlink(target)
    return target


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def directory_size(path: Path) -> int:
    """Total size in bytes, ignoring symlinks and unreadable entries."""
    total = 0
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
    return total
