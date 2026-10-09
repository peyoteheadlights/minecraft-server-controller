"""Updating the app from inside the app (house rule 2's second exception).

What it does, and nothing more (docs/security.md, "The in-app updater"):

1. **Check.** Once a day (``updates.check``, on by default) and when the
   owner selects "Check now", ask GitHub for this repo's latest release.
   Only ``api.github.com/repos/<this repo>/releases`` is asked, through the
   safe downloader. The release's "What's new" text is shown as it is.
2. **Install, only when the owner starts it** (``app.update``, never a
   helper's), after a confirmation in the dashboard:

   a. refuse a release that isn't newer than the running version, and a
      copy that wasn't installed by the Windows installer (a ``setup.ps1``
      folder runs the new installer once by hand instead);
   b. download the release's signed release file and its signature
      (agent/signing.py) and refuse the release unless the signature checks
      out with the key built into this copy; then download the setup
      program, from GitHub's release download address for this repo only,
      and refuse it unless its SHA-256 and size match the signed file;
   c. copy ``config.yaml``, ``.env`` and the database into
      ``<data folder>/updates/backup-<version>/`` first;
   d. keep the download as ``<setup>.exe.download`` (the agent never writes
      a program file), write ``updates/request.json`` (the version and the
      file's SHA-256),
      and ask Windows to run the "Minecraft Server Controller updater"
      task. That task was made by the installer, runs one fixed program from
      Program Files (``mcsc.exe apply-update``), which fetches the signed
      release file again and checks the signature and the setup file itself
      before it runs it.

   The installer then does what it always does for an update: restore
   point, stop, replace, start, check, and roll back by itself if the new
   version doesn't answer. The outcome is written to
   ``updates/last-update.json``, which this module turns into an event the
   next time the agent starts.

Nothing the dashboard sends becomes part of a command: the only program
this module starts is ``schtasks.exe /Run /TN <the updater task>``, with a
fixed argument list.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__, appinfo, downloads, signing
from .events import Event
from .winproc import NO_WINDOW

log = logging.getLogger("msc.updates")

REPO = downloads.REPO
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
UPDATER_TASK = "Minecraft Server Controller updater"
CHECK_EVERY = 24 * 3600
# The first check waits a while after the agent starts, so starting (and the
# test suite) never waits on GitHub.
FIRST_CHECK_DELAY = 15 * 60
MAX_SETUP_BYTES = 250 * 1024 * 1024
REQUEST_FILE = "request.json"
RESULT_FILE = "last-update.json"

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """Said to the owner as it is."""


def asset_name(version: str) -> str:
    return f"MinecraftServerController-Setup-{version}.exe"


def download_name(version: str) -> str:
    return asset_name(version) + ".download"


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.match((text or "").strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page: str
    published: str | None
    setup_url: str
    release_file_url: str
    signature_url: str
    size: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_release(data: Any) -> Release:
    """Read GitHub's answer for one release. Refuses anything that isn't a
    finished release of this repo with both files."""
    if not isinstance(data, dict):
        raise UpdateError("GitHub's answer about the latest version couldn't be read.")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("The latest release is a test version, so it isn't offered.")
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        raise UpdateError(f"The latest release's name ({tag or 'none'}) isn't a version number.")
    version = tag.lstrip("v")
    assets = {str(a.get("name")): a for a in data.get("assets") or [] if isinstance(a, dict)}
    setup = assets.get(asset_name(version))
    signed = assets.get(signing.release_file_name(version))
    signature = assets.get(signing.release_file_name(version) + ".sig")
    if not setup or not signed or not signature:
        raise UpdateError(
            f"Version {version} on GitHub doesn't have its setup file and signed release file yet."
        )
    for asset in (setup, signed, signature):
        url = str(asset.get("browser_download_url") or "")
        if not url.startswith(DOWNLOAD_PREFIX):
            raise UpdateError("A file in that release isn't on this app's own GitHub page.")
    size = setup.get("size")
    return Release(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "")[:20000],
        page=str(data.get("html_url") or f"https://github.com/{REPO}/releases"),
        published=data.get("published_at"),
        setup_url=setup["browser_download_url"],
        release_file_url=signed["browser_download_url"],
        signature_url=signature["browser_download_url"],
        size=int(size) if isinstance(size, int) else None,
    )


def release_file_urls(version: str) -> tuple[str, str]:
    """Where a version's signed release file and its signature are. Built
    here from the version, never taken from an answer."""
    name = signing.release_file_name(version)
    base = f"{DOWNLOAD_PREFIX}v{version}/{name}"
    return base, base + ".sig"


async def fetch_signed(version: str, public_key: str | None = None) -> signing.SignedRelease:
    """Download and check a version's signed release file. Raises
    UpdateError with one plain sentence when anything doesn't check out."""
    document_url, signature_url = release_file_urls(version)
    try:
        document = await downloads.fetch_bytes(document_url, max_bytes=signing.MAX_RELEASE_FILE)
        signature = await downloads.fetch_text(signature_url, max_bytes=1024)
        return signing.verify(
            document,
            signature,
            repo=REPO,
            version=version,
            file=asset_name(version),
            public_key=public_key,
        )
    except signing.SignatureError as exc:
        raise UpdateError(str(exc)) from exc
    except downloads.DownloadError as exc:
        raise UpdateError(f"The signed release file couldn't be downloaded: {exc}") from exc


def updates_dir(config) -> Path:
    return Path(config.data_dir) / "updates"


class Updater:
    def __init__(self, core):
        self.core = core
        self.latest: Release | None = None
        self.checked_at: float | None = None
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ status
    def install_kind(self) -> str:
        return "installer" if appinfo.installed() else "project"

    def status(self) -> dict[str, Any]:
        latest = self.latest
        available = bool(latest and is_newer(latest.version))
        kind = self.install_kind()
        reason = None
        if kind != "installer":
            reason = (
                "This copy was set up with setup.ps1, so it can't update itself. Download the "
                "installer from the release page and run it once; it moves your settings over, "
                "and later updates install from here."
            )
        elif not signing.has_key():
            reason = (
                "This copy was built without the key that checks updates are genuine, so it "
                "doesn't install them itself. Download the setup file from the release page and "
                "run it."
            )
        return {
            "current": __version__,
            "latest": latest.to_dict() if latest else None,
            "available": available,
            "checked_at": self.checked_at,
            "error": self.error,
            "checking": self.config.updates.check,
            "install_kind": kind,
            "can_install": available and kind == "installer" and signing.has_key(),
            "cannot_install_reason": reason if available else None,
            "last_result": self.last_result(),
        }

    @property
    def config(self):
        return self.core.config

    def last_result(self) -> dict[str, Any] | None:
        try:
            data = json.loads((updates_dir(self.config) / RESULT_FILE).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        keep = (
            "ok",
            "action",
            "version",
            "failed_step",
            "message",
            "rolled_back",
            "rollback_detail",
            "from_app",
            "notes",
            "certificate_renewed",
        )
        return {k: data.get(k) for k in keep}

    # ------------------------------------------------------------ checking
    async def check(self) -> dict[str, Any]:
        async with self._lock:
            try:
                data = await downloads.fetch_json(LATEST_URL)
                self.latest = parse_release(data)
                self.error = None
            except (downloads.DownloadError, UpdateError) as exc:
                self.error = str(exc)
            self.checked_at = time.time()
        if self.latest and is_newer(self.latest.version):
            seen = self.core.db.get_setting("updates:announced", None)
            if seen != self.latest.version:
                self.core.db.set_setting("updates:announced", self.latest.version)
                await self.core.bus.publish(
                    Event(
                        type="update_available",
                        level="info",
                        message=f"Version {self.latest.version} of this app is out",
                        data={"version": self.latest.version, "page": self.latest.page},
                    )
                )
        return self.status()

    async def _loop(self) -> None:
        await asyncio.sleep(FIRST_CHECK_DELAY)
        while True:
            if self.config.updates.check:
                try:
                    await self.check()
                except Exception:
                    log.debug("update check failed", exc_info=True)
            await asyncio.sleep(CHECK_EVERY)

    async def start(self) -> None:
        await self._announce_last_result()
        self._task = asyncio.create_task(self._loop(), name="update-check")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _announce_last_result(self) -> None:
        """Say how the last update went, once."""
        result = self.last_result()
        path = updates_dir(self.config) / RESULT_FILE
        if not result or not result.get("from_app"):
            return
        try:
            stamp = str(path.stat().st_mtime)
        except OSError:
            return
        if self.core.db.get_setting("updates:result_seen", None) == stamp:
            return
        self.core.db.set_setting("updates:result_seen", stamp)
        if result.get("ok"):
            event = Event(
                type="update_finished",
                level="success",
                message=f"Updated to version {result.get('version')}",
                data=result,
            )
        else:
            back = (
                "the previous version was put back"
                if result.get("rolled_back")
                else "the previous version couldn't be put back by itself"
            )
            event = Event(
                type="update_failed",
                level="error",
                message=f"The update to {result.get('version')} didn't work, so {back}",
                data=result,
            )
        await self.core.bus.publish(event)

    # ------------------------------------------------------------ installing
    def preflight(self) -> dict[str, Any]:
        """What the confirmation says: the version, and who is playing."""
        players = []
        unknown = False
        for ctx in self.core.servers.values():
            if ctx.server.status().get("state") != "running":
                continue
            count = ctx.players.online_count()
            if count is None:
                unknown = True
            elif count:
                players.append({"server": ctx.name, "players": count})
        return {
            **self.status(),
            "players_online": None if unknown else sum(p["players"] for p in players),
            "players": players,
        }

    def start_install(self, user: str):
        status = self.status()
        if not status["available"] or self.latest is None:
            raise UpdateError("There's no newer version to install. Select Check now first.")
        if not status["can_install"]:
            raise UpdateError(status["cannot_install_reason"])
        release = self.latest

        async def run(job) -> dict[str, Any]:
            folder = updates_dir(self.config) / release.version
            job.step("Checking the release's signature")
            signed = await fetch_signed(release.version)
            spec = downloads.FileSpec(
                url=release.setup_url,
                # Never saved as an .exe here (house rule: the agent writes
                # no programs); the update task makes the runnable copy.
                name=download_name(release.version),
                sha256=signed.sha256,
                size=signed.size,
                allow_unverified=False,
                max_bytes=MAX_SETUP_BYTES,
            )
            fetched = await downloads.download(spec, folder, job, "Downloading the update")
            job.step("Saving your settings and database first")
            backup = await asyncio.to_thread(self._backup, release.version)
            request = {
                "version": release.version,
                "file": fetched.path.name,
                "sha256": fetched.sha256,
                "requested_by": user,
                "requested_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "backup": str(backup),
            }
            (updates_dir(self.config) / REQUEST_FILE).write_text(
                json.dumps(request, indent=2), encoding="utf-8"
            )
            job.step("Starting the update")
            await asyncio.to_thread(run_updater_task)
            return {
                "version": release.version,
                "backup": str(backup),
                "message": "The update is starting. The dashboard is back in a minute or two.",
            }

        return self.core.jobs.start(
            "update", f"Updating to version {release.version}", run, user=user
        )

    def _backup(self, version: str) -> Path:
        folder = updates_dir(self.config) / f"backup-{version}"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        for source in (self.config.source, self.config.env_path):
            if source and Path(source).is_file():
                shutil.copy2(source, folder / Path(source).name)
        db = Path(self.config.database_path)
        if db.is_file():
            src = sqlite3.connect(str(db))
            try:
                dst = sqlite3.connect(str(folder / db.name))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        return folder


def run_updater_task() -> None:
    """Ask Windows to run the installer's update task. Fixed arguments; the
    task itself decides what runs (installer/apply_update.py)."""
    try:
        done = subprocess.run(
            ["schtasks.exe", "/Run", "/TN", UPDATER_TASK],
            capture_output=True,
            timeout=60,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"Windows couldn't start the update: {exc}") from exc
    if done.returncode != 0:
        raise UpdateError(
            "Windows couldn't start the update task. Run the setup from the Start menu once "
            "to repair it, then try again."
        )
