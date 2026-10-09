"""The fixed places an installed copy uses.

Program files go under Program Files and everything of yours (settings,
secrets, certificates, database, backups, crash evidence, logs) goes in one
app-data folder, so an update never depends on where anyone clicked.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent.config import default_data_root

PRODUCT = "Minecraft Server Controller"
PUBLISHER = "peyoteheadlights"
# The key under ...\CurrentVersion\Uninstall that lists the app in
# "Installed apps".
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MinecraftServerController"
UPDATER_TASK = "Minecraft Server Controller updater"
SETUP_COPY = "setup.exe"  # the installer kept in the program folder (repair and uninstall)
START_MENU_FOLDER = PRODUCT

RESTORE_POINTS = "restore-points"
UPDATES = "updates"
KEEP_RESTORE_POINTS = 3
KEEP_INSTALL_LOGS = 10


def default_program_dir() -> Path:
    base = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(base) / PRODUCT


def data_root() -> Path:
    return default_data_root()


def settings_dir(root: Path) -> Path:
    return root / "config"


def config_path(root: Path) -> Path:
    return settings_dir(root) / "config.yaml"


def env_path(root: Path) -> Path:
    return settings_dir(root) / ".env"


def logs_dir(root: Path) -> Path:
    return root / "logs"


def restore_points_dir(root: Path) -> Path:
    return root / RESTORE_POINTS


def updates_dir(root: Path) -> Path:
    return root / UPDATES


def start_menu_dir() -> Path:
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / START_MENU_FOLDER


_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """1.2.3 (anything after the third number is ignored), or None."""
    match = _VERSION_RE.match(text or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def compare_versions(new: str, old: str | None) -> str:
    """'newer', 'same', 'older' or 'unknown' (the old version can't be read)."""
    a, b = parse_version(new), parse_version(old)
    if a is None or b is None:
        return "unknown"
    return "newer" if a > b else "same" if a == b else "older"
