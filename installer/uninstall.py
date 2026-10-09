"""Removing the app (Windows "Installed apps", or the setup's Remove button).

It stops the app (any running Minecraft server is stopped cleanly through
it first), then removes the startup task, the update task, the firewall
rules, the Start Menu shortcuts, the "Installed apps" entry and the program
folder. Your data folder (settings, database, backups, logs) is kept unless
you tick "Also delete my settings and backups". Minecraft server folders
are never touched either way.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import layout
from .bootstrap import UPDATE_FOLDER_SUFFIX
from .installlog import InstallLog
from .system import System


def uninstall(
    program_dir: Path, data_root: Path, remove_data: bool = False, system: System | None = None
) -> dict[str, Any]:
    system = system or System()
    log = InstallLog(layout.logs_dir(data_root)) if not remove_data else None
    done: list[str] = []
    problems: list[str] = []

    def note(event: str, **fields: Any) -> None:
        if log:
            log.write(event, **fields)

    note("uninstall_started", program_dir=str(program_dir), remove_data=remove_data)
    system.host, port, tls, token = _settings(data_root)
    if log:
        log.hide(token)
    if system.agent_answers(port, tls):
        if token:
            try:
                for row in system.api(port, tls, token, "GET", "/servers")["servers"]:
                    if row.get("state") in ("running", "starting"):
                        system.api(port, tls, token, "POST", f"/servers/{row['id']}/server/stop")
                        done.append(f"stopped {row['name']}")
            except Exception as exc:
                problems.append(f"couldn't stop the Minecraft servers first: {exc}")
        system.stop_agent(port, tls)
        done.append("stopped the server panel")
    for name, action in (
        ("startup task", system.remove_startup),
        ("update task", system.remove_updater_task),
        ("Start menu shortcuts", system.remove_shortcuts),
        ("Installed apps entry", system.remove_uninstall_entry),
    ):
        try:
            action()
            done.append(f"removed the {name}")
        except Exception as exc:
            problems.append(f"the {name}: {exc}")
    try:
        script = Path(__file__).resolve().parent / "firewall.ps1"
        system.firewall(script, port, 0, remove=True)
        done.append("removed the firewall rules")
    except Exception as exc:
        problems.append(f"the firewall rules: {exc}")
    for folder in (program_dir, program_dir.with_name(program_dir.name + ".previous")):
        if folder.exists() and (folder / "install.json").is_file():
            shutil.rmtree(folder, ignore_errors=True)
            if folder.exists():
                problems.append(f"some files in {folder} were in use and are removed on restart")
            else:
                done.append(f"removed {folder}")
    # The last update's checked setup file (installer/apply_update.py).
    staging = program_dir.with_name(program_dir.name + UPDATE_FOLDER_SUFFIX)
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        done.append(f"removed {staging}")
    if remove_data and data_root.is_dir():
        inside = servers_inside(data_root)
        if inside:
            # Minecraft server folders are never removed, so neither is the
            # data folder that holds one.
            problems.append(
                f"{data_root} was kept because it holds a Minecraft server folder "
                f"({inside[0]}). Move or delete it yourself."
            )
        else:
            shutil.rmtree(data_root, ignore_errors=True)
            done.append(f"removed {data_root}")
    note("uninstall_finished", done=done, problems=problems)
    return {
        "ok": not problems,
        "done": done,
        "problems": problems,
        "kept": None if remove_data else str(data_root),
        "log": str(log.path) if log else None,
    }


def servers_inside(data_root: Path) -> list[str]:
    """The server folders in config.yaml that are inside the data folder."""
    try:
        from agent.config import Config

        config = Config.load(layout.config_path(data_root), layout.env_path(data_root))
        folders = [config.for_server(i).server_dir for i in config.server_ids]
    except Exception:
        return []
    root = data_root.resolve()
    found = []
    for folder in folders:
        try:
            folder.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        found.append(str(folder))
    return found


def _settings(data_root: Path) -> tuple[str, int, bool, str]:
    from .setup_tool import read_env
    from .system import read_address

    host, port, tls = read_address(layout.config_path(data_root))
    return host, port, tls, read_env(layout.env_path(data_root)).get("MCSC_API_TOKEN", "")
