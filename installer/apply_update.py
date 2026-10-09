"""``mcsc.exe apply-update``: what the "Minecraft Server Controller updater"
task runs, and nothing else runs it.

The dashboard can only *ask* for an update: the agent downloads the setup
program, checks it, and writes ``updates/request.json``. This program runs
from Program Files (which only Administrators can change), with the rights
an update needs, and trusts nothing in that request beyond a version
number:

1. the version must look like ``1.2.3`` and be newer than this copy;
2. the file must be ``updates/<version>/MinecraftServerController-Setup-
   <version>.exe.download`` (the name is built here, not read from the
   request);
3. the version's signed release file is fetched again, here, from this
   repo's GitHub release; its signature must check out with the key built
   into this copy (agent/signing.py), and the file's SHA-256 and size must
   match it.

Only then are the checked bytes written, as the setup program, to a folder
next to the program folder that only Administrators can change, and
started from there with fixed arguments (``--update --quiet
--from-app``), and this program exits so the update can replace it. The
outcome of each refusal is written where the dashboard reads it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from agent import appinfo
from agent.updates import (
    RESULT_FILE,
    UpdateError,
    asset_name,
    download_name,
    fetch_signed,
    is_newer,
    parse_version,
)
from agent.winproc import NO_WINDOW

from . import layout
from .installlog import InstallLog

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _refuse(data_root: Path, log: InstallLog, version: str, message: str) -> int:
    log.write("update_refused", version=version, message=message)
    result = {
        "ok": False,
        "action": "update",
        "version": version,
        "failed_step": "check",
        "message": message,
        "rolled_back": None,
        "from_app": True,
    }
    folder = layout.updates_dir(data_root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RESULT_FILE).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 1


def main(argv: list[str] | None = None) -> int:
    record = appinfo.install_record()
    if record is None:
        print("This copy wasn't installed by the installer, so it can't update itself.")
        return 2
    data_root = Path(record["data_root"])
    log = InstallLog(layout.logs_dir(data_root))
    request_path = layout.updates_dir(data_root) / "request.json"
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.write("update_refused", message="no update was requested")
        return 1
    finally:
        request_path.unlink(missing_ok=True)
    version = str(request.get("version") or "")
    if parse_version(version) is None:
        return _refuse(data_root, log, version, "The requested version isn't a version number.")
    if not is_newer(version, str(record.get("version") or "")):
        return _refuse(data_root, log, version, f"Version {version} isn't newer than this copy.")
    name = asset_name(version)
    download = layout.updates_dir(data_root) / version / download_name(version)
    if not download.is_file():
        return _refuse(data_root, log, version, "The downloaded update isn't there any more.")
    try:
        signed = asyncio.run(fetch_signed(version))
    except UpdateError as exc:
        return _refuse(data_root, log, version, str(exc))
    # Read once, check what was read, and run exactly that: the copy goes
    # into a folder next to the program folder, which only Administrators
    # can change, so nothing can swap it between the check and the start.
    data = download.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != signed.sha256 or len(data) != signed.size:
        return _refuse(
            data_root,
            log,
            version,
            "The downloaded update doesn't match the signed release, so it wasn't run.",
        )
    program = appinfo.program_dir()
    staging = staging_dir(program)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    setup = staging / name
    setup.write_bytes(data)
    download.unlink(missing_ok=True)
    arguments = ["--update", "--quiet", "--from-app", "--program-dir", str(program)]
    log.write("update_starting", version=version, sha256=actual, arguments=arguments)
    start(setup, arguments)
    return 0


def staging_dir(program: Path) -> Path:
    return program.with_name(program.name + ".update")


def start(setup: Path, arguments: list[str]) -> None:
    """Start the checked setup file on its own, so it outlives this program."""
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | NO_WINDOW
    try:
        subprocess.Popen(
            [str(setup), *arguments],
            creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except OSError:
        subprocess.Popen([str(setup), *arguments], creationflags=flags, close_fds=True)
