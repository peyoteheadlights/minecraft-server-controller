"""Find an existing copy of the app before asking anything.

Two kinds are recognised:

* ``installer``: a program folder holding ``install.json`` (written by this
  installer), with its settings in the app-data folder.
* ``project``: an older ``setup.ps1`` install, a project folder with
  ``agent/main.py``, ``config/config.yaml`` and ``.env`` or ``.venv``.

Where to look: the Windows startup task's working folder, the "Installed
apps" entry, the data folder's own settings, and the standard places people
unzip the project. Each folder found is described from what is on disk
(its version file, how many servers its config.yaml lists), never guessed.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.appinfo import INSTALL_RECORD

from . import layout

INSTALLER, PROJECT = "installer", "project"


@dataclass
class Found:
    kind: str  # installer | project
    program_dir: Path
    config_path: Path
    env_path: Path
    version: str | None
    server_count: int | None
    data_root: Path | None = None
    used_by_startup_task: bool = False
    seen_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("program_dir", "config_path", "env_path", "data_root"):
            data[key] = str(data[key]) if data[key] is not None else None
        return data

    def describe(self) -> str:
        """One plain sentence for the first screen."""
        version = f" {self.version}" if self.version else ""
        if self.server_count is None:
            servers = ""
        elif self.server_count == 1:
            servers = " with 1 server"
        else:
            servers = f" with {self.server_count} servers"
        return f"We found {layout.PRODUCT}{version}{servers}."


_VERSION_LINE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


def read_project_version(folder: Path) -> str | None:
    """The version a project folder declares, read from its file (it is not
    imported, so nothing in the old copy runs)."""
    try:
        match = _VERSION_LINE.search((folder / "agent" / "__init__.py").read_text("utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def count_servers(config_path: Path) -> int | None:
    """How many servers config.yaml lists, or None if it can't be read."""
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    servers = data.get("servers")
    if isinstance(servers, list) and servers:
        return len(servers)
    server = data.get("server")
    if isinstance(server, dict):
        directory = str(server.get("directory") or "")
        if not directory.strip() or "path\\to" in directory or "path/to" in directory:
            return 0
        return 1
    return 0


def classify(folder: Path) -> Found | None:
    """Describe the copy in a folder, or None if there isn't one."""
    try:
        folder = Path(folder)
        if not folder.is_dir():
            return None
    except OSError:
        return None
    record_path = folder / INSTALL_RECORD
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = None
        if isinstance(record, dict) and record.get("data_root"):
            root = Path(record["data_root"])
            config = layout.config_path(root)
            return Found(
                kind=INSTALLER,
                program_dir=folder,
                config_path=config,
                env_path=layout.env_path(root),
                version=str(record.get("version") or "") or None,
                server_count=count_servers(config),
                data_root=root,
            )
    config = folder / "config" / "config.yaml"
    if (folder / "agent" / "main.py").is_file() and config.is_file():
        if (folder / ".env").is_file() or (folder / ".venv").is_dir():
            return Found(
                kind=PROJECT,
                program_dir=folder,
                config_path=config,
                env_path=folder / ".env",
                version=read_project_version(folder),
                server_count=count_servers(config),
            )
    return None


def standard_places() -> list[Path]:
    """Where people usually unzip or clone the project."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    names = ("minecraft-server-controller", "minecraft-server-control", "mcsc")
    parents = [home, home / "Desktop", home / "Documents", home / "Downloads", Path("C:/")]
    places = [layout.default_program_dir()]
    for parent in parents:
        for name in names:
            places.append(parent / name)
            places.append(parent / f"{name}-main")
    return places


def find_installs(
    *,
    task_folder: Path | None = None,
    registry_folder: Path | None = None,
    data_root: Path | None = None,
    places: Iterable[Path] | None = None,
) -> list[Found]:
    """Every copy found, the one the startup task uses first.

    The probes are passed in so tests (and other systems) can say what
    Windows would report; ``probe_windows()`` fills them in for real."""
    seen: dict[str, Found] = {}

    def add(folder: Path | None, source: str) -> None:
        if folder is None:
            return
        found = classify(folder)
        if found is None:
            return
        key = os.path.normcase(str(found.program_dir.resolve()))
        existing = seen.setdefault(key, found)
        if source not in existing.seen_by:
            existing.seen_by.append(source)
        if source == "startup task":
            existing.used_by_startup_task = True

    add(task_folder, "startup task")
    add(registry_folder, "Installed apps")
    root = data_root or layout.data_root()
    if layout.config_path(root).is_file():
        # The data folder's own settings mean an installer copy put them
        # there; its program folder is the standard one unless the
        # Installed apps entry said otherwise.
        add(layout.default_program_dir(), "data folder")
    for place in places if places is not None else standard_places():
        add(place, "standard place")
    return sorted(seen.values(), key=lambda f: (not f.used_by_startup_task, f.kind != INSTALLER))


def probe_windows() -> dict[str, Path | None]:
    """Ask Windows where the startup task runs and what Installed apps lists."""
    probes: dict[str, Path | None] = {"task_folder": None, "registry_folder": None}
    if os.name != "nt":
        return probes
    try:
        from . import autostart

        task = autostart.query_task()
        if task and task.get("working_directory"):
            probes["task_folder"] = Path(task["working_directory"])
    except Exception:
        pass
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, layout.UNINSTALL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
            probes["registry_folder"] = Path(value) if value else None
    except (OSError, ImportError):
        pass
    return probes
