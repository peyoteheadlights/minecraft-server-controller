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
from collections.abc import Iterable
from pathlib import Path

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-() ]{0,190}$")
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
EXECUTABLE_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".msi",
    ".scr",
    ".com",
    ".vbs",
    ".js",
    ".jse",
    ".wsf",
    ".wsh",
    ".dll",
    ".lnk",
    ".reg",
    ".py",
    ".jsp",
}


class PathSafetyError(ValueError):
    """Raised when a path or filename fails a safety rule."""


def safe_filename(name: str, allowed_extensions: set[str] | None = None) -> str:
    """Validate a single filename. Returns it unchanged, or raises."""
    if not name or name in (".", ".."):
        raise PathSafetyError("No file name was given.")
    if "/" in name or "\\" in name or "\0" in name:
        raise PathSafetyError(f"{name!r} is a path, not a file name.")
    if name != name.strip() or name.endswith("."):
        raise PathSafetyError(
            f"{name!r} starts or ends with a space or a dot, which Windows can't handle."
        )
    if not SAFE_NAME_RE.match(name):
        raise PathSafetyError(f"{name!r} has characters in it that a file name can't have.")
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        raise PathSafetyError(
            f"Windows keeps the name {name!r} for itself, so a file can't be called that."
        )
    suffix = Path(name).suffix.lower()
    if suffix in EXECUTABLE_EXTENSIONS:
        raise PathSafetyError(f"{suffix} files are never downloaded or written by this agent")
    if allowed_extensions is not None and suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise PathSafetyError(
            f"Only {allowed} files are allowed here, got {suffix or 'no extension'}"
        )
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
        raise PathSafetyError("That path leads outside the folder it has to stay in.")
    return candidate


def assert_not_symlink(path: Path) -> Path:
    p = Path(path)
    if p.is_symlink():
        raise PathSafetyError(f"{p} is a shortcut to somewhere else, so it wasn't followed.")
    if os.name == "nt" and p.exists():
        try:
            attrs = os.stat(p, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
            if attrs & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PathSafetyError(
                    f"{p} points somewhere else on the disk, so it wasn't followed."
                )
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


def directory_size(path: Path, exclude: Iterable[Path] = ()) -> int:
    """Total size in bytes, ignoring symlinks, unreadable entries and any
    folder in ``exclude`` (and everything under it)."""
    total = 0
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    skip = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if not os.path.islink(os.path.join(root, d))
            and os.path.normcase(os.path.abspath(os.path.join(root, d))) not in skip
        ]
        for name in files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            try:
                total += os.path.getsize(full)
            except OSError:
                continue
    return total


def _system_folders() -> list[Path]:
    """Folders a Minecraft server must never be registered in or above."""
    names = ["SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"]
    found = [Path(os.environ[n]) for n in names if os.environ.get(n)]
    if os.name != "nt":
        found += [Path(p) for p in ("/bin", "/boot", "/dev", "/etc", "/proc", "/sys", "/usr")]
    return found


def check_new_server_folder(
    value: str,
    protected: Iterable[Path] = (),
    registered: Iterable[tuple[str, Path]] = (),
) -> Path:
    """Validate a folder a new server is about to be created in.

    The same rules as check_server_folder, except that the folder may not
    exist yet (its parent must) and, if it does exist, it must be empty:
    a new server never writes into a folder that already holds files.
    Nothing is created here.
    """
    raw = (value or "").strip()
    if not raw or "\0" in raw:
        raise PathSafetyError("Enter the folder the new server should live in.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PathSafetyError(
            "Enter the full path to the folder, for example C:\\Minecraft\\Survival"
        )
    if path.exists():
        assert_not_symlink(path)
        if not path.is_dir():
            raise PathSafetyError(f"{path} is a file, not a folder.")
        if any(path.iterdir()):
            raise PathSafetyError(
                f"{path} already has files in it. Pick an empty or new folder, or add the "
                "existing server instead."
            )
    parent = path.parent
    if not parent.is_dir():
        raise PathSafetyError(f"{parent} doesn't exist, so the new folder can't be made there.")
    assert_not_symlink(parent)
    resolved = (parent.resolve() / path.name) if not path.exists() else path.resolve()
    if resolved.parent == resolved:
        raise PathSafetyError("A whole drive can't be a server folder; pick a folder inside it.")
    home = Path.home().resolve()
    if resolved == home:
        raise PathSafetyError("Your home folder can't be a server folder; pick a folder inside it.")
    for system in _system_folders():
        if is_inside(system, resolved):
            raise PathSafetyError(f"{path} is inside a system folder ({system}).")
    for folder in protected:
        folder = Path(folder)
        if is_inside(folder, resolved) or is_inside(resolved, folder):
            raise PathSafetyError(f"{path} overlaps this app's own folder {folder}.")
    for name, folder in registered:
        if is_inside(Path(folder), resolved) or is_inside(resolved, Path(folder)):
            raise PathSafetyError(f"{path} overlaps the folder of the server '{name}'.")
    return resolved


def check_server_folder(
    value: str,
    jar: str,
    protected: Iterable[Path] = (),
    registered: Iterable[tuple[str, Path]] = (),
) -> Path:
    """Validate a folder someone wants to register as a Minecraft server.

    This is the one place a folder path arrives from the dashboard. It must
    be an existing, absolute, real folder that holds the server jar, that is
    not a drive root or a system folder, that neither contains nor sits
    inside the agent's own folders, and that no other server already uses.
    Nothing is created, moved or deleted here.
    """
    raw = (value or "").strip()
    if not raw or "\0" in raw:
        raise PathSafetyError("Enter the folder that contains your Minecraft server")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PathSafetyError(
            "Enter the full path to the folder, for example C:\\Minecraft\\Survival"
        )
    assert_not_symlink(path)
    if not path.is_dir():
        raise PathSafetyError(f"{path} does not exist or is not a folder")
    resolved = path.resolve()
    if resolved.parent == resolved:
        raise PathSafetyError(
            "A whole drive cannot be a server folder; pick the server's own folder"
        )
    home = Path.home().resolve()
    if resolved == home:
        raise PathSafetyError(
            "Your home folder cannot be a server folder; pick the server's own folder"
        )
    for system in _system_folders():
        if is_inside(system, resolved):
            raise PathSafetyError(f"{path} is inside a system folder ({system})")
    for folder in protected:
        folder = Path(folder)
        if is_inside(folder, resolved) or is_inside(resolved, folder):
            raise PathSafetyError(f"{path} overlaps the agent's own folder {folder}")
    for name, folder in registered:
        if is_inside(Path(folder), resolved) or is_inside(resolved, Path(folder)):
            raise PathSafetyError(f"{path} overlaps the folder of the server '{name}'")
    safe_filename(jar, {".jar"})
    jar_path = resolved / jar
    if not jar_path.is_file() or jar_path.is_symlink():
        raise PathSafetyError(f"{jar} was not found in {path}")
    return resolved
