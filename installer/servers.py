"""The servers a new install starts with.

The installer asks where each existing Minecraft server is, with its name
and color. Each folder is checked by the same function the dashboard's
"Add a server that's already in a folder" uses (``check_server_folder``),
its port is read from its own ``server.properties``, and its type is
suggested from the files in it. The suggestion is only the first choice on
the screen; the person can change it, and nothing about the server's
version is shown until its console prints it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent import servertypes
from agent.config import Config
from agent.ports import read_properties_port
from agent.security.paths import PathSafetyError, check_server_folder
from agent.servertypes.create import new_server_id
from agent.servertypes.install import find_args_file

DEFAULT_JARS = ("fabric-server-launch.jar", "server.jar")


class ServerFolderError(ValueError):
    pass


def suggest_type(folder: Path) -> str:
    """The type a folder most looks like, from the start files in it."""
    folder = Path(folder)
    for type_id, kind in servertypes.TYPES.items():
        if kind.launch == "args_file" and find_args_file(folder, type_id):
            return type_id
    for type_id, kind in servertypes.TYPES.items():
        if kind.launch == "jar" and kind.jar != "server.jar" and (folder / kind.jar).is_file():
            return type_id
    if (folder / "server.jar").is_file():
        return "vanilla"
    return servertypes.RECOMMENDED


def describe_folder(value: str, protected: list[Path]) -> dict[str, Any]:
    """What the screen shows after a folder is picked: ok, or one plain
    sentence saying what's wrong with it."""
    folder = Path((value or "").strip().strip('"')).expanduser()
    if not value.strip() or not folder.is_dir():
        return {
            "ok": False,
            "problem": "That folder isn't there. Pick the folder your server is in.",
        }
    type_id = suggest_type(folder)
    try:
        jar = _jar_for(folder, type_id)
        check_server_folder(str(folder), jar, protected=protected)
    except PathSafetyError as exc:
        return {"ok": False, "problem": str(exc)}
    return {
        "ok": True,
        "folder": str(folder.resolve()),
        "type": type_id,
        "type_name": servertypes.get(type_id).name,
        "name": folder.name,
        "port": read_properties_port(folder),
    }


def _jar_for(folder: Path, type_id: str) -> str:
    kind = servertypes.get(type_id)
    if kind.launch == "args_file":
        return ""
    names = (kind.jar, *DEFAULT_JARS) if kind.jar else DEFAULT_JARS
    return next((j for j in names if (folder / j).is_file()), names[0])


def entries(picks: list[dict[str, Any]], java: str, protected: list[Path]) -> list[dict[str, Any]]:
    """config.yaml entries for the picked folders, checked, with ids."""
    out: list[dict[str, Any]] = []
    registered: list[tuple[str, Path]] = []
    for pick in picks:
        name = str(pick.get("name") or "").strip()[:60] or Path(str(pick["folder"])).name
        type_id = servertypes.get(pick.get("type") or None).id
        kind = servertypes.get(type_id)
        folder_value = str(pick.get("folder") or "")
        jar = _jar_for(Path(folder_value), type_id)
        try:
            directory = check_server_folder(
                folder_value, jar, protected=protected, registered=registered
            )
        except PathSafetyError as exc:
            raise ServerFolderError(str(exc)) from exc
        args_file = ""
        if kind.launch == "args_file":
            args_file = find_args_file(directory, type_id) or ""
            if not args_file:
                raise ServerFolderError(
                    f"{directory} has no {kind.name} start file, so it doesn't look like a "
                    f"set-up {kind.name} server. Run {kind.name}'s installer there first."
                )
        entry = {
            "id": new_server_id(name, [e["id"] for e in out]),
            "name": name,
            "directory": str(directory),
            "type": type_id,
            "jar": jar,
            "args_file": args_file,
            "java": java,
            "port": read_properties_port(directory) or 25565 + len(out),
        }
        out.append(entry)
        registered.append((name, directory))
    return out


def write_servers(config_path: Path, env_path: Path, new_entries: list[dict[str, Any]]) -> None:
    """Replace the example's placeholder server with the picked ones."""
    if not new_entries:
        return
    config = Config.load(config_path, env_path)
    config._data["servers"] = []
    for entry in new_entries:
        config.add_server(entry)
    config.save(config_path)
