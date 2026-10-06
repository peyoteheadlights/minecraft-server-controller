"""The folder picker: browsing the PC's folders from the dashboard.

Used wherever a folder is chosen (a world in the saves folder, a drive or
cloud folder for off-PC backup copies) so nobody has to type a Windows path.
It only lists folders, never files or their contents, and only the owner can
use it (files.browse). Choosing a folder still goes through the check of the
feature that uses it (check_folder, inspect_folder); this only reads names.

Each folder says whether it holds a Minecraft world (a level.dat inside), so
the world picker can point at them.
"""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

MAX_ENTRIES = 500


class BrowseError(ValueError):
    pass


def drives() -> list[dict[str, Any]]:
    """The PC's drives (Windows) or the file system root (elsewhere)."""
    if os.name != "nt":
        return [{"name": "/", "path": "/"}]
    found = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            found.append({"name": f"{letter}:", "path": root})
    return found


def shortcuts() -> list[dict[str, Any]]:
    """Folders people usually want: home, Desktop, cloud folders that are
    set up on this PC, and single-player Minecraft's saves. Only ones that
    exist are listed."""
    from .worldimport import saves_folder

    home = Path.home()
    candidates: list[tuple[str, Path | None]] = [
        ("home", home),
        ("desktop", home / "Desktop"),
        (
            "onedrive",
            Path(os.environ["OneDrive"]) if os.environ.get("OneDrive") else home / "OneDrive",
        ),
        ("google_drive", home / "Google Drive"),
        ("google_drive", Path("G:\\My Drive") if os.name == "nt" else None),
        ("dropbox", home / "Dropbox"),
        ("saves", saves_folder()),
    ]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, path in candidates:
        if path is None or key in seen:
            continue
        try:
            if path.is_dir():
                found.append({"key": key, "path": str(path)})
                seen.add(key)
        except OSError:
            continue
    return found


def listing(value: str | None) -> dict[str, Any]:
    """The folders inside one folder. With no folder: drives and shortcuts."""
    if not value:
        return {
            "path": None,
            "parent": None,
            "folders": [],
            "drives": drives(),
            "shortcuts": shortcuts(),
        }
    raw = value.strip()
    if "\0" in raw:
        raise BrowseError("That isn't a folder path.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise BrowseError("Choose the whole path to a folder.")
    try:
        if not path.is_dir():
            raise BrowseError(f"{path} isn't there, or isn't a folder.")
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except PermissionError as exc:
        raise BrowseError(f"Windows doesn't let this app look inside {path}.") from exc
    except OSError as exc:
        raise BrowseError(f"{path} can't be read: {exc.strerror or exc}") from exc
    folders: list[dict[str, Any]] = []
    for entry in entries:
        if len(folders) >= MAX_ENTRIES:
            break
        try:
            if entry.is_symlink() or not entry.is_dir() or entry.name.startswith("$"):
                continue
            world = os.path.isfile(os.path.join(entry.path, "level.dat"))
        except OSError:
            continue
        folders.append({"name": entry.name, "path": entry.path, "world": world})
    parent = path.parent if path.parent != path else None
    return {
        "path": str(path),
        "parent": str(parent) if parent else None,
        "folders": folders,
        "truncated": len(folders) >= MAX_ENTRIES,
        "world": (path / "level.dat").is_file(),
    }
