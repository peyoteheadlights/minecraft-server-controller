"""The install, update and repair steps behind the installer's screens.

One engine does all of it, whether the person runs the installer or the
dashboard starts an update (``--update --from-app``):

* **install**: a PC with no copy of the app.
* **update**: an installer copy of an older version.
* **repair**: the same version again.
* **migrate**: an older ``setup.ps1`` project folder. Its settings are
  copied into the app-data folder and checked (file counts and SHA-256),
  the startup task is pointed at the new copy, and the old folder is never
  deleted; the dashboard offers to remove it some days later.

Rules it keeps:

* Going backwards is refused before anything changes (database changes
  only go forward).
* Before changing anything on a PC that already has the app, a restore
  point is saved (settings, secrets, database, and the previous program
  folder kept beside the new one). If a later step fails, the engine rolls
  back by itself, starts the old version again, and says it did.
* Everything that's yours is kept: settings, passwords, phone alert keys,
  certificates, servers and backups. Questions already answered are not
  asked again.
* Minecraft servers that are running are stopped cleanly through the app
  first (only after asking, when players are online), and started again
  afterwards.
* The progress bar moves only for finished work (``installer/progress.py``)
  and every step is written to the install log without secrets
  (``installer/installlog.py``).
"""

from __future__ import annotations

import json
import shutil
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import __version__, appinfo

from . import detect, fileops, layout, restorepoint
from .installlog import InstallLog
from .progress import Progress
from .system import System, SystemError_

INSTALL, UPDATE, REPAIR, MIGRATE = "install", "update", "repair", "migrate"
OLD_COPY_RECORD = "old-copy.json"
UPDATE_RESULT = "last-update.json"


class StepFailed(Exception):
    """One plain sentence for the screen, and the real error for details."""

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.message = message
        self.details = details


class Refused(StepFailed):
    """Refused before anything changed (for example, going backwards)."""


@dataclass
class Choices:
    action: str = INSTALL
    program_dir: Path = field(default_factory=layout.default_program_dir)
    data_root: Path = field(default_factory=layout.data_root)
    found: detect.Found | None = None
    # New installs: [{"folder", "name", "color", "type"}]
    servers: list[dict[str, Any]] = field(default_factory=list)
    password: str | None = None
    start_with_pc: bool = True
    allow_devices: bool = True
    phone_alerts: bool = False
    push_contact: str = ""
    import_file: Path | None = None
    import_to: Path | None = None
    import_passphrase: str | None = None
    java_path: str | None = None  # an existing java.exe chosen for the servers
    install_java: int | None = None  # a Temurin version to install
    # Existing installs: the servers to switch to that Java (or to java_path)
    java_servers: list[str] = field(default_factory=list)
    setup_exe: Path | None = None  # this installer, kept for repair and uninstall
    from_app: bool = False

    def to_log(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "program_dir": str(self.program_dir),
            "data_root": str(self.data_root),
            "found": self.found.to_dict() if self.found else None,
            "servers": [
                {k: v for k, v in s.items() if k in ("folder", "name", "type")}
                for s in self.servers
            ],
            "password_given": bool(self.password),
            "start_with_pc": self.start_with_pc,
            "allow_devices": self.allow_devices,
            "phone_alerts": self.phone_alerts,
            "import_file": str(self.import_file) if self.import_file else None,
            "install_java": self.install_java,
            "java_path": self.java_path,
            "java_servers": self.java_servers,
            "from_app": self.from_app,
        }


@dataclass
class Result:
    ok: bool
    action: str
    version: str
    failed_step: str | None = None
    message: str = ""
    details: str = ""
    rolled_back: bool | None = None  # None: there was nothing to roll back
    rollback_detail: str = ""
    log_path: str = ""
    certificate_renewed: bool = False
    dashboard_url: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def decide_action(found: detect.Found | None, version: str = __version__) -> tuple[str, str]:
    """What running this installer would do, and why, before anything changes.
    Raises Refused for an older version."""
    if found is None:
        return INSTALL, "No copy of the app was found, so this is a new install."
    verdict = layout.compare_versions(version, found.version)
    if verdict == "older":
        raise Refused(
            f"This installer is version {version}, but version {found.version} is already "
            "installed. It can't go back, because your data has already been upgraded "
            f"for {found.version}. Download {found.version} or newer instead.",
            f"installer {version} < installed {found.version} at {found.program_dir}",
        )
    if found.kind == detect.PROJECT:
        return MIGRATE, "An older copy set up with setup.ps1 was found; it will be moved."
    if verdict == "same":
        return REPAIR, f"Version {version} is already installed, so it will be repaired."
    return UPDATE, f"Version {found.version or 'unknown'} will be updated to {version}."


class Engine:
    def __init__(
        self,
        choices: Choices,
        source_dir: Path,
        system: System | None = None,
        log: InstallLog | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        version: str = __version__,
    ):
        self.c = choices
        self.source_dir = Path(source_dir)
        self.system = system or System()
        self.version = version
        self.log = log or InstallLog(layout.logs_dir(choices.data_root))
        self.log.hide(choices.password, choices.import_passphrase)
        self.progress = Progress(on_change=on_progress)
        self.point: restorepoint.RestorePoint | None = None
        self.previous_program: Path | None = None
        self.new_program_created = False
        self.created_settings: list[Path] = []
        self.previous_launch: dict[str, str] | None = None
        self.stopped_servers: list[str] = []
        self.agent_stopped = False
        self.certificate_renewed = False
        self.notes: list[str] = []
        self._plan()

    # ------------------------------------------------------------ paths
    @property
    def config_path(self) -> Path:
        return layout.config_path(self.c.data_root)

    @property
    def env_path(self) -> Path:
        return layout.env_path(self.c.data_root)

    @property
    def existing(self) -> bool:
        return self.c.action in (UPDATE, REPAIR, MIGRATE)

    # ------------------------------------------------------------ plan
    def _plan(self) -> None:
        c, add = self.c, self.progress.add
        add("check", "Checking this PC", 1)
        if self.existing:
            add("restore", "Saving a restore point", 5)
            add("stop", "Stopping the server panel", 4)
        add("program", "Copying the app's files", 30)
        add(
            "settings",
            {
                INSTALL: "Saving your settings",
                MIGRATE: "Moving your settings",
            }.get(c.action, "Checking your settings"),
            4,
        )
        if c.import_file:
            add("import", "Importing from your other PC", 15)
        if c.install_java:
            add("java", f"Installing Java {c.install_java}", 25)
        if c.action == INSTALL and c.servers:
            add("servers", "Adding your servers", 2)
        if (c.install_java or c.java_path) and (
            (self.existing and c.java_servers) or (c.action == INSTALL and not c.servers)
        ):
            add("java_servers", "Pointing your servers at the new Java", 1)
        add("password", "Saving your password", 2)
        add("certificate", "Setting up secure connection", 5)
        add("push", "Setting up phone alerts", 1)
        add("firewall", "Letting your phone and other devices connect", 3)
        add("startup", "Making the server panel start with your PC", 3)
        add("menu", "Adding it to the Start menu and Installed apps", 3)
        add("start", "Starting the server panel", 4)
        add("verify", "Checking the server panel answers", 6)
        add("finish", "Finishing up", 2)

    # ------------------------------------------------------------ run
    def run(self) -> Result:
        self.log.write(
            "install_started",
            version=self.version,
            choices=self.c.to_log(),
            log=str(self.log.path),
        )
        steps: list[tuple[str, Callable[[], str | None]]] = [
            ("check", self.step_check),
            ("restore", self.step_restore),
            ("stop", self.step_stop),
            ("program", self.step_program),
            ("settings", self.step_settings),
            ("import", self.step_import),
            ("java", self.step_java),
            ("servers", self.step_servers),
            ("java_servers", self.step_java_servers),
            ("password", self.step_password),
            ("certificate", self.step_certificate),
            ("push", self.step_push),
            ("firewall", self.step_firewall),
            ("startup", self.step_startup),
            ("menu", self.step_menu),
            ("start", self.step_start),
            ("verify", self.step_verify),
            ("finish", self.step_finish),
        ]
        planned = {s.key for s in self.progress.steps}
        for key, action in steps:
            if key not in planned:
                continue
            name = self.progress.step(key).name
            self.progress.start(key)
            self.log.write("step_started", step=key, name=name)
            try:
                skipped = action()
            except Exception as exc:
                return self._failed(key, exc)
            if skipped:
                self.progress.skip(key, skipped)
                self.log.write("step_skipped", step=key, reason=skipped)
            else:
                self.progress.finish(key)
                self.log.write("step_finished", step=key, result="ok")
        self.progress.complete()
        result = Result(
            ok=True,
            action=self.c.action,
            version=self.version,
            log_path=str(self.log.path),
            certificate_renewed=self.certificate_renewed,
            dashboard_url=self._dashboard_url(),
            notes=self.notes,
        )
        self._record_result(result)
        self.log.write("install_finished", result="ok", action=self.c.action)
        return result

    def _failed(self, key: str, exc: Exception) -> Result:
        from .setup_tool import LockDownError

        if isinstance(exc, StepFailed):
            message, details = exc.message, exc.details
        elif isinstance(exc, SystemError_):
            message, details = str(exc), exc.details
        elif isinstance(exc, LockDownError):
            message, details = f"{exc.message} {exc.fix}", exc.problem
        else:
            message = "Something unexpected went wrong in this step."
            details = f"{type(exc).__name__}: {exc}"
        details = details or "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.progress.fail(key, message, self.log.scrub(details))
        self.log.write(
            "step_failed",
            step=key,
            message=message,
            error=details[-4000:],
            traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[
                -4000:
            ],
        )
        rolled_back, rollback_detail = self.roll_back()
        result = Result(
            ok=False,
            action=self.c.action,
            version=self.version,
            failed_step=key,
            message=message,
            details=self.log.scrub(details),
            rolled_back=rolled_back,
            rollback_detail=rollback_detail,
            log_path=str(self.log.path),
        )
        self._record_result(result)
        self.log.write(
            "install_finished",
            result="failed",
            failed_step=key,
            rolled_back=rolled_back,
            rollback_detail=rollback_detail,
        )
        return result

    # ------------------------------------------------------------ helpers
    def _settings(self) -> tuple[int, bool, str]:
        """The dashboard port, whether it uses HTTPS, and the API token."""
        from .setup_tool import read_env

        port, tls = 8765, True
        try:
            import yaml

            data = yaml.safe_load(self._current_config().read_text(encoding="utf-8")) or {}
            network = data.get("network") or {}
            port = int(network.get("port") or port)
            tls = bool((data.get("tls") or {}).get("enabled", True))
        except Exception:
            pass
        token = read_env(self._current_env()).get("MCSC_API_TOKEN", "")
        self.log.hide(token)
        return port, tls, token

    def _current_config(self) -> Path:
        """The settings in use now: the data folder's, or before a move, the
        old copy's."""
        if self.config_path.is_file() or self.c.found is None:
            return self.config_path
        return self.c.found.config_path

    def _current_env(self) -> Path:
        if self.c.found and self.c.action == MIGRATE and not self.env_path.is_file():
            return self.c.found.env_path
        return self.env_path

    def _setup_context(self):
        from .setup_tool import Context

        return Context(
            mode="setup",
            interactive=False,
            root=self.c.program_dir,
            config_file=self.config_path,
            env_file=self.env_path,
            password=self.c.password,
            push_contact=self.c.push_contact,
            say=lambda line: self.log.write("detail", text=line),
        )

    def _dashboard_url(self) -> str | None:
        try:
            from agent.config import Config

            return Config.load(self.config_path, self.env_path).base_url
        except Exception:
            return None

    def _record_result(self, result: Result) -> None:
        """Where the dashboard reads how the last update went."""
        try:
            folder = layout.updates_dir(self.c.data_root)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / UPDATE_RESULT).write_text(
                json.dumps({**result.to_dict(), "from_app": self.c.from_app}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------ steps
    def step_check(self) -> str | None:
        decide_action(self.c.found, self.version)
        if not self.source_dir.is_dir():
            raise StepFailed(
                "The installer's own files are missing. Download the installer again.",
                f"no program files at {self.source_dir}",
            )
        need = fileops.folder_size(self.source_dir) * 2
        free = shutil.disk_usage(_existing_parent(self.c.program_dir)).free
        if free < need:
            raise StepFailed(
                f"There isn't enough free space on the drive ({need // 2**20} MB needed). "
                "Free some space and select Try again.",
                f"free {free} bytes, need {need}",
            )
        self.log.write(
            "detected",
            found=self.c.found.to_dict() if self.c.found else None,
            free_bytes=free,
            admin=self.system.is_admin(),
        )
        return None

    def step_restore(self) -> str | None:
        found = self.c.found
        assert found is not None
        self.point = restorepoint.create(
            self.c.data_root,
            version=found.version,
            config_path=found.config_path,
            env_path=found.env_path,
            program_dir=found.program_dir,
            reason=f"before {self.c.action} to {self.version}",
            report=self.progress.reporter("restore"),
        )
        self.log.write("restore_point_saved", folder=str(self.point.folder))
        return None

    def step_stop(self) -> str | None:
        port, tls, token = self._settings()
        if not self.system.agent_answers(port, tls):
            return "The server panel wasn't running."
        if token:
            try:
                rows = self.system.api(port, tls, token, "GET", "/servers")["servers"]
            except Exception as exc:
                rows = []
                self.log.write("servers_not_listed", error=str(exc))
            for row in rows:
                if row.get("state") in ("running", "starting"):
                    self.system.api(port, tls, token, "POST", f"/servers/{row['id']}/server/stop")
                    self.stopped_servers.append(row["id"])
            if self.stopped_servers:
                self.log.write("servers_stopping", servers=self.stopped_servers)
                self._wait_servers_stopped(port, tls, token)
        self.agent_stopped = True
        if not self.system.stop_agent(port, tls):
            raise StepFailed(
                "The server panel didn't stop. Restart the PC and select Try again.",
                f"port {port} still answers after stopping the task",
            )
        return None

    def _wait_servers_stopped(self, port: int, tls: bool, token: str) -> None:
        import time

        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            rows = self.system.api(port, tls, token, "GET", "/servers")["servers"]
            if all(r.get("state") in ("stopped", "crashed") for r in rows):
                return
            time.sleep(2)
        raise StepFailed(
            "A Minecraft server didn't stop in time. Stop it from the dashboard, "
            "then select Try again.",
            "servers still running after 180 s",
        )

    def step_program(self) -> str | None:
        target = self.c.program_dir
        incoming = target.with_name(target.name + ".incoming")
        shutil.rmtree(incoming, ignore_errors=True)
        pairs = [
            (self.source_dir / rel, incoming / rel)
            for rel in fileops.list_files(self.source_dir, skip=(appinfo.INSTALL_RECORD,))
        ]
        if self.c.setup_exe and Path(self.c.setup_exe).is_file():
            pairs.append((Path(self.c.setup_exe), incoming / layout.SETUP_COPY))
        copied = fileops.copy_files(pairs, self.progress.reporter("program"))
        record = {
            "version": self.version,
            "data_root": str(self.c.data_root),
            "installed_by": "installer",
        }
        (incoming / appinfo.INSTALL_RECORD).write_text(json.dumps(record, indent=2), "utf-8")
        if target.exists():
            previous = target.with_name(target.name + ".previous")
            shutil.rmtree(previous, ignore_errors=True)
            try:
                target.rename(previous)
            except OSError as exc:
                raise StepFailed(
                    "Some of the app's files are still in use. Restart the PC and select "
                    "Try again.",
                    f"rename {target} -> {previous}: {exc}",
                ) from exc
            self.previous_program = previous
        incoming.rename(target)
        self.new_program_created = True
        self.log.write("program_copied", files=copied.files, bytes=copied.bytes, to=str(target))
        return None

    def step_settings(self) -> str | None:
        settings = layout.settings_dir(self.c.data_root)
        self.system.secure_data_folder(self.c.data_root)
        settings.mkdir(parents=True, exist_ok=True)
        if self.c.action == MIGRATE:
            return self._move_settings()
        if self.config_path.is_file():
            self._check_config()
            return None
        if self.c.action != INSTALL:
            raise StepFailed(
                "Your settings file is missing from the app's data folder.",
                f"{self.config_path} not found",
            )
        example = Path(self.source_dir / "_internal" / "config" / "config.example.yaml")
        if not example.is_file():
            example = appinfo.PROJECT_ROOT / "config" / "config.example.yaml"
        shutil.copyfile(example, self.config_path)
        self.created_settings.append(self.config_path)
        self._check_config()
        return None

    def _move_settings(self) -> str | None:
        found = self.c.found
        assert found is not None
        pairs = []
        for source in (
            found.config_path,
            found.config_path.with_name("config.yaml.original"),
            found.config_path.with_name("config.yaml.bak"),
            found.env_path,
        ):
            target = layout.settings_dir(self.c.data_root) / source.name
            if source.is_file():
                if target.is_file():
                    keep = target.with_name(target.name + ".before-move")
                    shutil.copyfile(target, keep)
                pairs.append((source, target))
        copied = fileops.copy_files(pairs, self.progress.reporter("settings"))
        self.created_settings.extend(t for _, t in pairs)
        problems = [
            f"different: {dst}"
            for src, dst in pairs
            if fileops.sha256_file(src) != fileops.sha256_file(dst)
        ]
        if problems or copied.files != len(pairs):
            raise StepFailed(
                "Your settings couldn't be copied exactly, so nothing was switched over.",
                "; ".join(problems),
            )
        record = {
            "path": str(found.program_dir),
            "version": found.version,
            "moved_at": _now(),
            "files": {str(d): h for d, h in copied.hashes.items()},
        }
        (self.c.data_root / OLD_COPY_RECORD).write_text(json.dumps(record, indent=2), "utf-8")
        self.log.write("settings_moved", files=copied.files, from_=str(found.program_dir))
        self._check_config()
        self._anchor_server_folders(found.program_dir)
        return None

    def _anchor_server_folders(self, old_folder: Path) -> None:
        """A setup.ps1 copy ran from its own folder, so a server folder
        written as a relative path (``servers/survival``) meant one inside
        it. The installed copy runs from Program Files, so such a path is
        written out in full, pointing where it always did."""
        from agent.config import Config

        config = Config.load(self.config_path, self.env_path)
        changed = {}
        for server_id in config.server_ids:
            directory = config.for_server(server_id).server.directory.strip()
            if directory and not Path(directory).expanduser().is_absolute():
                full = str((old_folder / directory).resolve())
                config.set_server_value(server_id, "server.directory", full)
                changed[server_id] = full
        if not changed:
            return
        extras = [
            self.config_path.with_name(self.config_path.name + suffix)
            for suffix in (".original", ".bak")
        ]
        new_extras = [path for path in extras if not path.exists()]
        config.save(self.config_path)
        self.created_settings.extend(path for path in new_extras if path.exists())
        self.log.write("server_folders_made_absolute", servers=changed)

    def _check_config(self) -> None:
        from agent.config import Config

        try:
            Config.load(self.config_path, self.env_path)
        except Exception as exc:
            raise StepFailed(
                "Your settings file couldn't be read, so nothing was changed in it.",
                f"{self.config_path}: {exc}",
            ) from exc

    def step_import(self) -> str | None:
        from agent.transfer import TransferError, import_all

        from .setup_tool import write_env_value

        target = self.c.import_to or Path.home() / "Minecraft Servers"
        try:
            result = import_all(
                Path(self.c.import_file or ""),
                target,
                self.config_path,
                self.env_path,
                passphrase=self.c.import_passphrase,
                write_env=write_env_value,
            )
        except (TransferError, OSError) as exc:
            raise StepFailed(f"The import stopped: {exc}", str(exc)) from exc
        self.log.write(
            "imported",
            servers=len(result["servers"]),
            files=result["files"],
            backups=result["backups"],
            secrets=bool(result["secrets"]),
        )
        return None

    def step_java(self) -> str | None:
        from . import java_setup

        major = int(self.c.install_java or 0)
        folder = layout.updates_dir(self.c.data_root) / "java"
        fetched = java_setup.download_temurin(major, folder, self._java_report())
        self.log.write("java_downloaded", version=fetched["version"], sha256=fetched["sha256"])
        msi = Path(fetched["path"])
        self.system.install_msi(
            java_setup.install_command(msi, layout.logs_dir(self.c.data_root) / "java-install.log")
        )
        found = java_setup.installed_java(major)
        if found is None:
            raise StepFailed(
                f"Java {major} was installed but doesn't run. Select Try again.",
                "no working java.exe under Eclipse Adoptium after msiexec",
            )
        self.c.java_path = found.path
        msi.unlink(missing_ok=True)
        self.log.write("java_installed", path=found.path, version=found.version)
        return None

    def _java_report(self) -> Callable[[int, int | None], None]:
        def report(done: int, total: int | None) -> None:
            if total:
                self.progress.advance("java", done, total)

        return report

    def step_servers(self) -> str | None:
        from . import servers

        java = self.c.java_path or "java"
        try:
            entries = servers.entries(
                self.c.servers, java, protected=[self.c.program_dir, self.c.data_root]
            )
        except servers.ServerFolderError as exc:
            raise StepFailed(str(exc)) from exc
        servers.write_servers(self.config_path, self.env_path, entries)
        self.log.write("servers_added", servers=[e["id"] for e in entries])
        return None

    def step_java_servers(self) -> str | None:
        """An update or repair with Java picked for some servers: those
        servers run on it from now on, and the others keep the Java they
        have. A new install with no server yet sets it on the starting
        settings, so the first server made in the dashboard uses it."""
        from agent.config import Config

        java = self.c.java_path
        if not java:
            raise StepFailed("There's no Java to use. Select Try again.")
        config = Config.load(self.config_path, self.env_path)
        picked = self.c.java_servers if self.existing else config.server_ids
        changed = []
        for server_id in picked:
            if config.has_server(server_id):
                config.set_server_value(server_id, "server.java", java)
                changed.append(server_id)
        if not changed:
            return "Those servers aren't in your settings any more."
        config.save(self.config_path)
        self.log.write("java_servers", servers=changed, java=java)
        return None

    def step_password(self) -> str | None:
        from agent.security.auth import hash_password

        from .setup_tool import read_env, step_secrets, write_env_value

        has_password = (
            read_env(self.env_path).get("MCSC_ADMIN_PASSWORD_HASH", "").startswith("pbkdf2")
        )
        if has_password and not (self.c.action == INSTALL and self.c.password):
            step_secrets(self._setup_context())  # adds an API token if one is missing
            return "Your existing password is kept."
        if has_password and self.c.password:
            # A new install tried again with a different password: use the
            # one typed this time.
            write_env_value(
                self.env_path, "MCSC_ADMIN_PASSWORD_HASH", hash_password(self.c.password)
            )
        ctx = self._setup_context()
        step = step_secrets(ctx)
        if step.status != "OK":
            raise StepFailed(
                "The password couldn't be saved. Go back and type it again.", step.detail
            )
        if not self.env_path.is_file():
            raise StepFailed("The password couldn't be saved.", "no .env written")
        self.created_settings.append(self.env_path)
        return None

    def step_certificate(self) -> str | None:
        from agent.security.tls import inspect_certificate

        from .setup_tool import _load_config, step_certificate

        ctx = self._setup_context()
        before = None
        try:
            config = _load_config(ctx)
            before = inspect_certificate(config.tls_certificate, config.tls_private_key)
        except Exception:
            pass
        step = step_certificate(ctx)
        if step.status == "FAIL":
            raise StepFailed(
                "The secure connection couldn't be set up.", f"{step.detail}. {step.fix}"
            )
        renewed = step.detail.startswith("created") and bool(before and before.parsed)
        if renewed:
            self.certificate_renewed = True
            self.notes.append(
                "The secure connection was renewed, so each phone has to scan the code again."
            )
        return None if step.status == "OK" else step.detail

    def step_push(self) -> str | None:
        from .setup_tool import PUSH_KEYS, read_env, step_push_keys

        has_keys = bool(read_env(self.env_path).get(PUSH_KEYS[0]))
        if not has_keys and not self.c.phone_alerts:
            return "Skipped. You can turn on phone alerts later in the app's alert settings."
        step = step_push_keys(self._setup_context())
        if step.status == "FAIL":
            raise StepFailed("The phone alert keys couldn't be made.", step.detail)
        return "Your phone alert keys are kept." if has_keys else None

    def step_firewall(self) -> str | None:
        if not self.c.allow_devices:
            if self.c.action == INSTALL:
                return "Skipped: only this PC can open the dashboard."
            return "Left as it was."
        port, _, _ = self._settings()
        from agent.config import Config

        redirect = Config.load(self.config_path, self.env_path).tls.http_redirect_port
        script = Path(__file__).resolve().parent / "firewall.ps1"
        self.system.firewall(script, port, redirect)
        return None

    def step_startup(self) -> str | None:
        self.previous_launch = self.system.previous_startup_launch()
        mode = "boot" if self.c.start_with_pc else "manual"
        if self.existing and self.previous_launch:
            # Already answered once: keep how it starts.
            mode = self.previous_launch.get("mode") or mode
        launch = {
            "command": str(self.c.program_dir / appinfo.AGENT_EXE),
            "arguments": "--launched-by task",
            "working_directory": str(self.c.program_dir),
        }
        self.system.register_startup(launch, mode)
        self.log.write("startup_task", mode=mode, **launch)
        return None

    def step_menu(self) -> str | None:
        self.system.register_updater_task(self.c.program_dir)
        links = self.system.create_shortcuts(self.c.program_dir)
        size_kb = fileops.folder_size(self.c.program_dir) // 1024
        self.system.write_uninstall_entry(self.c.program_dir, self.version, size_kb)
        self.log.write("registered", shortcuts=links, size_kb=size_kb)
        return None

    def step_start(self) -> str | None:
        self.system.start_agent()
        return None

    def step_verify(self) -> str | None:
        port, tls, _ = self._settings()
        if not self.system.wait_for_agent(port, tls):
            raise StepFailed(
                f"The server panel didn't answer on port {port}. Another program may be "
                "using that port: close it and select Try again.",
                f"no answer from 127.0.0.1:{port}/api/health within the wait",
            )
        self.log.write("agent_answered", port=port, tls=tls)
        return None

    def step_finish(self) -> str | None:
        port, tls, token = self._settings()
        done = []
        if self.c.action == INSTALL and self.c.servers and token:
            listed = self.system.api(port, tls, token, "GET", "/servers")["servers"]
            by_name = {row["name"]: row["id"] for row in listed}
            for pick in self.c.servers:
                server_id = by_name.get(str(pick.get("name") or ""))
                if server_id and pick.get("color"):
                    self.system.api(
                        port,
                        tls,
                        token,
                        "PUT",
                        f"/servers/{server_id}/color",
                        {"color": pick["color"]},
                    )
                    done.append(f"color for {server_id}")
        for server_id in self.stopped_servers:
            self.system.api(port, tls, token, "POST", f"/servers/{server_id}/server/start")
            done.append(f"started {server_id}")
        if self.previous_program and self.previous_program.exists():
            # The update is checked, so the previous program isn't needed any
            # more (the restore point keeps the settings and database).
            shutil.rmtree(self.previous_program, ignore_errors=True)
        self.log.write("finished", done=done)
        return None if done else "Nothing else to do."

    # ------------------------------------------------------------ roll back
    def roll_back(self) -> tuple[bool | None, str]:
        """Put the PC back the way it was. Returns (rolled back?, what was
        done). None means nothing had been changed that needed it."""
        changed = self.new_program_created or self.created_settings
        if not changed and not self.agent_stopped and not self.stopped_servers:
            return None, "Nothing had been changed yet."
        actions = []
        try:
            if not changed and not self.agent_stopped:
                # Only Minecraft servers were stopped, through the app,
                # which is still running: start them again.
                port, tls, token = self._settings()
                for server_id in self.stopped_servers:
                    self.system.api(port, tls, token, "POST", f"/servers/{server_id}/server/start")
                actions.append("started the Minecraft servers it had stopped")
                self.log.write("rolled_back", actions=actions)
                return True, "; ".join(actions)
            port, tls, _ = self._settings()
            self.system.stop_agent(port, tls)
            if self.new_program_created:
                shutil.rmtree(self.c.program_dir, ignore_errors=True)
                actions.append("removed the new program files")
                if self.previous_program and self.previous_program.exists():
                    self.previous_program.rename(self.c.program_dir)
                    actions.append("put the previous program back")
            if self.point is not None:
                if self.c.action == MIGRATE:
                    for path in self.created_settings:
                        path.unlink(missing_ok=True)
                    (self.c.data_root / OLD_COPY_RECORD).unlink(missing_ok=True)
                    actions.append("removed the copied settings (the old copy wasn't changed)")
                else:
                    restorepoint.restore(self.point)
                    actions.append("put your settings and database back")
            if self.previous_launch and self.previous_launch.get("command"):
                launch = {
                    k: self.previous_launch[k]
                    for k in ("command", "arguments", "working_directory")
                }
                self.system.register_startup(launch, self.previous_launch.get("mode") or "manual")
                actions.append("pointed the startup task back at the old copy")
            if self.existing:
                self.system.start_agent()
                port, tls, token = self._settings()
                if self.system.wait_for_agent(port, tls):
                    actions.append("started the previous version again")
                    for server_id in self.stopped_servers:
                        self.system.api(
                            port, tls, token, "POST", f"/servers/{server_id}/server/start"
                        )
                else:
                    actions.append("the previous version didn't answer after starting")
                    self.log.write("rollback_incomplete", actions=actions)
                    return False, "; ".join(actions)
        except Exception as exc:
            self.log.write("rollback_failed", error=f"{type(exc).__name__}: {exc}", actions=actions)
            return False, "; ".join([*actions, f"then: {exc}"])
        self.log.write("rolled_back", actions=actions)
        return True, "; ".join(actions)


def _existing_parent(path: Path) -> Path:
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def _now() -> str:
    import datetime as dt

    return dt.datetime.now().astimezone().isoformat(timespec="seconds")
