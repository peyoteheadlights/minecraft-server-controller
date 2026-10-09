"""Where this copy of the app lives, and where its settings are.

There are two kinds of install:

* **Installed by the Windows installer** (Phase 7). The program is a built
  folder under Program Files, which the agent's own account can only read.
  The installer writes ``install.json`` next to the program, naming the data
  folder. Settings (``config.yaml`` and ``.env``) live in that data folder's
  ``config`` folder, and logs in its ``logs`` folder, so an update can
  replace the whole program folder without touching anything of yours.
* **A project folder** (``setup.ps1``, or a developer's clone). Settings are
  ``config/config.yaml`` and ``.env`` in the project folder, as before.

This module only uses the standard library, because the startup log needs
it before anything else is imported.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_RECORD = "install.json"
# The program's two files in an installed copy: one runs with no window (the
# startup task and the Start Menu use it), the other is for typed commands.
AGENT_EXE = "MinecraftServerController.exe"
CLI_EXE = "mcsc.exe"
# The Start menu entry that repairs, updates or removes the app and installs
# Java for servers (installer/system.py makes it).
SETUP_SHORTCUT = "Minecraft Server Controller setup"


def frozen() -> bool:
    """True when running from the installer's built program, not from source."""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """The folder holding the program: the built folder, or the project."""
    override = os.environ.get("MCSC_PROGRAM_DIR")
    if override:
        return Path(override)
    if frozen():
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def install_record(folder: Path | None = None) -> dict[str, Any] | None:
    """What the installer recorded about this copy, or None for a project
    folder. Never raises: a broken record reads as no record."""
    path = (folder or program_dir()) / INSTALL_RECORD
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("data_root") else None


def installed() -> bool:
    return install_record() is not None


def settings_dir() -> Path:
    """The folder holding config.yaml (and, for installed copies, .env)."""
    record = install_record()
    if record:
        return Path(record["data_root"]) / "config"
    return PROJECT_ROOT / "config"


def default_config_path() -> Path:
    return settings_dir() / "config.yaml"


def default_env_path() -> Path:
    record = install_record()
    if record:
        return Path(record["data_root"]) / "config" / ".env"
    return PROJECT_ROOT / ".env"


def log_dir() -> Path:
    """Where the startup and setup logs go before config.yaml is read."""
    override = os.environ.get("MCSC_STARTUP_LOG_DIR")
    if override:
        return Path(override)
    record = install_record()
    if record:
        return Path(record["data_root"]) / "logs"
    return PROJECT_ROOT / "logs"


def agent_launch() -> dict[str, str]:
    """The program, arguments and folder the Windows startup task runs.

    An installed copy runs its own built program; a project folder runs
    ``pythonw -m agent.main`` from the project folder, as before."""
    if frozen() or installed():
        folder = program_dir()
        return {
            "command": str(folder / AGENT_EXE),
            "arguments": "--launched-by task",
            "working_directory": str(folder),
        }
    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    return {
        "command": str(pythonw if pythonw.is_file() else exe),
        "arguments": "-m agent.main --launched-by task",
        "working_directory": str(PROJECT_ROOT),
    }


def web_dir() -> Path:
    """The dashboard's files. PyInstaller puts data files under the
    bundle's own folder, which ``__file__`` already points into."""
    return Path(__file__).resolve().parent / "web"
