"""The Windows installer's engine: finding old copies, moving a setup.ps1
install, updating an installer copy, rolling back a failed update, refusing
to go backwards, honest progress, and an install log with no secrets.

Windows itself (Task Scheduler, the firewall, the registry, the running
app) is replaced by FakeSystem, which records what would have happened.
The real calls are exercised on windows-latest in CI.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from agent.config import SECRET_ENV_KEYS
from agent.security.auth import hash_password
from installer import detect, engine, fileops, layout, restorepoint
from installer.engine import Choices, Engine
from installer.progress import Progress

PROJECT = Path(__file__).resolve().parent.parent
PASSWORD = "a secret password 9"


class FakeSystem:
    """Stands in for installer.system.System."""

    host = "127.0.0.1"
    tailscale: str | None = None

    def __init__(self):
        self.running = False
        self.hosts_asked: list[str] = []
        self.calls: list[tuple] = []
        self.servers = [{"id": "main", "name": "Survival", "state": "stopped"}]
        self.fail_start = False
        self.start_count = 0
        self.task_launch = None

    def is_admin(self):
        return True

    def agent_answers(self, port, tls=True):
        self.hosts_asked.append(self.host)
        return self.running

    def wait_for_agent(self, port, tls, timeout=90.0):
        self.hosts_asked.append(self.host)
        return self.running

    def tailscale_address(self):
        return self.tailscale

    def api(self, port, tls, token, method, path, body=None):
        self.calls.append(("api", method, path, body))
        if path == "/servers":
            return {"servers": self.servers}
        if path.endswith("/server/stop"):
            for row in self.servers:
                row["state"] = "stopped"
        return {"ok": True}

    def stop_agent(self, port, tls):
        self.calls.append(("stop_agent",))
        self.running = False
        return True

    def start_agent(self):
        self.calls.append(("start_agent",))
        self.start_count += 1
        # A failing update: the new version never answers, the old one does.
        self.running = not (self.fail_start and self.start_count == 1)

    def register_startup(self, launch, mode):
        self.calls.append(("register_startup", launch["command"], mode))
        self.task_launch = {**launch, "mode": mode}
        return {}

    def previous_startup_launch(self):
        return self.task_launch

    def firewall(self, script, port, redirect_port, remove=False):
        self.calls.append(("firewall", port))

    def register_updater_task(self, program_dir):
        self.calls.append(("updater_task", str(program_dir)))

    def create_shortcuts(self, program_dir):
        self.calls.append(("shortcuts",))
        return ["Minecraft Server Controller.lnk"]

    def write_uninstall_entry(self, program_dir, version, size_kb):
        self.calls.append(("uninstall_entry", version))

    def secure_data_folder(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)

    def install_msi(self, command):
        self.calls.append(("msi", command))

    def remove_startup(self):
        self.calls.append(("remove_startup",))

    def remove_updater_task(self):
        self.calls.append(("remove_updater_task",))

    def remove_shortcuts(self):
        self.calls.append(("remove_shortcuts",))

    def remove_uninstall_entry(self):
        self.calls.append(("remove_uninstall_entry",))

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture(autouse=True)
def clean_secrets(monkeypatch):
    """Loading a .env puts its values in the environment; registering the
    keys here takes them out again after each test."""
    for key in SECRET_ENV_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.setattr("agent.tailscale.tailscale_binary", lambda: None)


@pytest.fixture
def program_files(tmp_path):
    """What the new version's setup.exe unpacks: a stand-in program folder."""
    folder = tmp_path / "payload"
    (folder / "_internal" / "config").mkdir(parents=True)
    (folder / "MinecraftServerController.exe").write_bytes(b"new agent")
    (folder / "mcsc.exe").write_bytes(b"new cli")
    (folder / "_internal" / "lib.bin").write_bytes(b"x" * 5000)
    shutil.copy(
        PROJECT / "config" / "config.example.yaml",
        folder / "_internal" / "config" / "config.example.yaml",
    )
    return folder


@pytest.fixture
def places(tmp_path):
    return {"program": tmp_path / "Program Files" / layout.PRODUCT, "data": tmp_path / "data"}


def make_server(tmp_path, name="Survival") -> Path:
    server = tmp_path / name
    server.mkdir()
    (server / "fabric-server-launch.jar").write_bytes(b"jar")
    (server / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    return server


def make_setup_ps1_install(tmp_path, data_root: Path) -> Path:
    """An older install made with setup.ps1: a project folder with .venv,
    config/config.yaml (two servers, data in data_root), .env with a
    password, and a backup in the database."""
    project = tmp_path / "minecraft-server-controller"
    (project / "agent").mkdir(parents=True)
    (project / "agent" / "main.py").write_text("# the agent\n", encoding="utf-8")
    (project / "agent" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (project / ".venv").mkdir()
    (project / "config").mkdir()
    one, two = make_server(tmp_path, "One"), make_server(tmp_path, "Two")
    (project / "config" / "config.yaml").write_text(
        "# my settings\n"
        f"paths:\n  data_dir: '{data_root}'\n"
        "servers:\n"
        f"  - id: one\n    name: One\n    directory: '{one}'\n"
        f"  - id: two\n    name: Two\n    directory: '{two}'\n    port: 25566\n",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        f"MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH={hash_password(PASSWORD)}\n"
        "MCSC_API_TOKEN=token-from-the-old-install\n",
        encoding="utf-8",
    )
    data_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_root / "mcsc.sqlite3")
    db.execute("CREATE TABLE backups (id INTEGER PRIMARY KEY, path TEXT)")
    db.execute("INSERT INTO backups (path) VALUES ('backup-1.zip')")
    db.commit()
    db.close()
    (data_root / "backups").mkdir()
    (data_root / "backups" / "backup-1.zip").write_bytes(b"world")
    return project


def make_installer_copy(places, version="1.0.0", servers=1) -> detect.Found:
    """An install made by an earlier release of this installer."""
    program, data = places["program"], places["data"]
    program.mkdir(parents=True)
    (program / "MinecraftServerController.exe").write_bytes(b"old agent")
    (program / "install.json").write_text(
        json.dumps({"version": version, "data_root": str(data)}), encoding="utf-8"
    )
    (data / "config").mkdir(parents=True)
    entries = "".join(
        f"  - id: s{i}\n    name: S{i}\n    directory: '{data / f's{i}'}'\n" for i in range(servers)
    )
    (data / "config" / "config.yaml").write_text(
        f"paths:\n  data_dir: '{data}'\nservers:\n{entries}", encoding="utf-8"
    )
    from agent.notifications.push import generate_keys

    public, private = generate_keys()
    (data / "config" / ".env").write_text(
        f"MCSC_ADMIN_PASSWORD_HASH={hash_password(PASSWORD)}\nMCSC_API_TOKEN=tok-1234567\n"
        f"MCSC_VAPID_PUBLIC_KEY={public}\nMCSC_VAPID_PRIVATE_KEY={private}\n",
        encoding="utf-8",
    )
    db = sqlite3.connect(data / "mcsc.sqlite3")
    db.execute("CREATE TABLE t (v TEXT)")
    db.execute("INSERT INTO t VALUES ('before')")
    db.commit()
    db.close()
    found = detect.classify(program)
    assert found is not None
    return found


def run_engine(choices, program_files, system=None, version="1.2.0"):
    system = system or FakeSystem()
    eng = Engine(choices, program_files, system=system, version=version)
    return eng, eng.run(), system


# ====================================================================
# finding old copies
# ====================================================================
def test_a_setup_ps1_install_is_found_and_described(tmp_path, places):
    project = make_setup_ps1_install(tmp_path, places["data"])
    found = detect.find_installs(
        task_folder=project, data_root=places["data"], places=[tmp_path / "nowhere"]
    )
    assert len(found) == 1
    assert found[0].kind == detect.PROJECT
    assert found[0].version == "1.0.0"
    assert found[0].server_count == 2
    assert found[0].used_by_startup_task
    assert found[0].describe() == "We found Minecraft Server Controller 1.0.0 with 2 servers."


def test_several_copies_list_the_startup_task_one_first(tmp_path, places):
    project = make_setup_ps1_install(tmp_path, places["data"])
    installed = make_installer_copy(places)
    found = detect.find_installs(
        task_folder=installed.program_dir, places=[project], data_root=tmp_path / "x"
    )
    assert [f.kind for f in found] == [detect.INSTALLER, detect.PROJECT]
    assert found[0].used_by_startup_task and not found[1].used_by_startup_task


def test_a_folder_that_is_not_the_app_is_not_mistaken_for_one(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("x: 1\n")
    assert detect.classify(tmp_path) is None
    assert detect.classify(tmp_path / "missing") is None


# ====================================================================
# moving a setup.ps1 install
# ====================================================================
def test_a_setup_ps1_install_is_moved_verified_and_left_in_place(tmp_path, places, program_files):
    project = make_setup_ps1_install(tmp_path, places["data"])
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    found = detect.classify(project)
    action, _ = engine.decide_action(found, "1.2.0")
    assert action == engine.MIGRATE
    choices = Choices(
        action=action, program_dir=places["program"], data_root=places["data"], found=found
    )
    eng, result, system = run_engine(choices, program_files)
    assert result.ok, result.message + result.details

    # settings and password copied exactly; the backup and database kept
    moved = places["data"] / "config"
    # (Making the certificate this old copy never had then saved its paths,
    # which keeps the file as it was copied in config.yaml.original.)
    copied = moved / "config.yaml.original"
    assert copied.read_bytes() == (project / "config" / "config.yaml").read_bytes()
    assert detect.count_servers(moved / "config.yaml") == 2
    assert (moved / ".env").read_bytes() == (project / ".env").read_bytes()
    assert (places["data"] / "backups" / "backup-1.zip").read_bytes() == b"world"
    # the old folder is untouched
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == before
    # the startup task points at the new copy
    assert system.called("register_startup")[-1][1] == str(
        places["program"] / "MinecraftServerController.exe"
    )
    # the cleanup card has what it needs
    record = json.loads((places["data"] / engine.OLD_COPY_RECORD).read_text())
    assert record["path"] == str(project)
    # and the new copy knows where its data is
    installed = json.loads((places["program"] / "install.json").read_text())
    assert installed == {
        "version": "1.2.0",
        "data_root": str(places["data"]),
        "installed_by": "installer",
    }
    assert detect.classify(places["program"]).kind == detect.INSTALLER


# ====================================================================
# updating an installer copy
# ====================================================================
def test_an_installer_copy_is_updated_keeping_everything(tmp_path, places, program_files):
    found = make_installer_copy(places, "1.0.0", servers=2)
    env_before = found.env_path.read_text()
    system = FakeSystem()
    system.running = True
    system.servers = [{"id": "s0", "name": "S0", "state": "running"}]
    system.task_launch = {
        "command": str(places["program"] / "MinecraftServerController.exe"),
        "arguments": "--launched-by task",
        "working_directory": str(places["program"]),
        "mode": "logon",
    }
    choices = Choices(
        action=engine.UPDATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, _ = run_engine(choices, program_files, system)
    assert result.ok, result.message + result.details
    assert (places["program"] / "MinecraftServerController.exe").read_bytes() == b"new agent"
    assert not (places["program"].with_name(layout.PRODUCT + ".previous")).exists()
    # passwords and phone alert keys kept: phones keep getting alerts
    assert found.env_path.read_text() == env_before
    # the running server was stopped cleanly first and started again after
    paths = [c[2] for c in system.called("api")]
    assert "/servers/s0/server/stop" in paths and "/servers/s0/server/start" in paths
    assert paths.index("/servers/s0/server/stop") < paths.index("/servers/s0/server/start")
    # how it starts with Windows was already answered, so it is kept
    assert system.called("register_startup")[-1][2] == "logon"
    # a restore point was saved
    point = restorepoint.latest(places["data"])
    assert point is not None and point.version == "1.0.0"
    assert set(point.manifest["files"]) == {"config.yaml", ".env", "database.sqlite3"}


def test_an_update_points_only_the_picked_servers_at_the_new_java(places, program_files):
    found = make_installer_copy(places, "1.0.0", servers=2)
    java = r"C:\Program Files\Eclipse Adoptium\jre-21\bin\java.exe"
    choices = Choices(
        action=engine.UPDATE,
        program_dir=places["program"],
        data_root=places["data"],
        found=found,
        java_path=java,
        java_servers=["s1", "gone"],
    )
    _, result, _ = run_engine(choices, program_files)
    assert result.ok, result.message + result.details
    from agent.config import Config

    config = Config.load(found.config_path, found.env_path)
    assert config.server_settings("s1").java == java
    assert config.server_settings("s0").java == "java"  # not picked: unchanged


def test_the_same_version_again_is_a_repair(places):
    found = make_installer_copy(places, "1.2.0")
    assert engine.decide_action(found, "1.2.0")[0] == engine.REPAIR


def test_going_backwards_is_refused_before_anything_changes(tmp_path, places, program_files):
    found = make_installer_copy(places, "2.0.0")
    with pytest.raises(engine.Refused) as refused:
        engine.decide_action(found, "1.2.0")
    assert "can't go back" in refused.value.message
    before = {p: p.read_bytes() for p in places["data"].rglob("*") if p.is_file()}
    choices = Choices(
        action=engine.UPDATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, system = run_engine(choices, program_files)
    assert not result.ok and result.failed_step == "check"
    assert result.rolled_back is None  # nothing had been changed
    after = {
        p: p.read_bytes()
        for p in places["data"].rglob("*")
        if p.is_file() and "logs" not in p.parts and "updates" not in p.parts
    }
    assert after == before
    assert (places["program"] / "MinecraftServerController.exe").read_bytes() == b"old agent"
    assert not system.called("stop_agent")


# ====================================================================
# a failed update rolls back by itself
# ====================================================================
def test_a_failed_update_rolls_back_to_the_restore_point(tmp_path, places, program_files):
    found = make_installer_copy(places, "1.0.0")
    config_before = found.config_path.read_bytes()
    env_before = found.env_path.read_bytes()
    system = FakeSystem()
    system.running = True
    system.fail_start = True  # the new version never answers

    choices = Choices(
        action=engine.UPDATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    eng = Engine(choices, program_files, system=system, version="1.2.0")
    # Pretend the new version changed the database before it failed.
    real_start = system.start_agent

    def start_and_touch():
        if system.start_count == 0:
            db = sqlite3.connect(places["data"] / "mcsc.sqlite3")
            db.execute("UPDATE t SET v = 'after'")
            db.commit()
            db.close()
        real_start()

    system.start_agent = start_and_touch
    result = eng.run()

    assert not result.ok and result.failed_step == "verify"
    assert result.rolled_back is True, result.rollback_detail
    assert "started the previous version again" in result.rollback_detail
    assert (places["program"] / "MinecraftServerController.exe").read_bytes() == b"old agent"
    assert found.config_path.read_bytes() == config_before
    assert found.env_path.read_bytes() == env_before
    db = sqlite3.connect(places["data"] / "mcsc.sqlite3")
    assert db.execute("SELECT v FROM t").fetchone()[0] == "before"
    db.close()
    snapshot = eng.progress.snapshot()
    assert snapshot["failed"]["key"] == "verify"
    assert not snapshot["finished"]
    # the dashboard can tell what happened once it is back
    last = json.loads((places["data"] / "updates" / engine.UPDATE_RESULT).read_text())
    assert last["ok"] is False and last["rolled_back"] is True


# ====================================================================
# a new install, and its log
# ====================================================================
def test_a_new_install_sets_everything_up(tmp_path, places, program_files):
    server = make_server(tmp_path)
    system = FakeSystem()
    choices = Choices(
        action=engine.INSTALL,
        program_dir=places["program"],
        data_root=places["data"],
        servers=[{"folder": str(server), "name": "Survival", "color": "teal"}],
        password=PASSWORD,
        java_path="/opt/java/bin/java",
    )
    system.running = False
    original_start = system.start_agent

    def start():
        original_start()
        system.servers = [{"id": "survival", "name": "Survival", "state": "stopped"}]

    system.start_agent = start
    _, result, _ = run_engine(choices, program_files, system)
    assert result.ok, result.message + result.details
    env = (places["data"] / "config" / ".env").read_text()
    assert "MCSC_ADMIN_PASSWORD_HASH=pbkdf2_sha256$" in env
    assert PASSWORD not in env
    config = (places["data"] / "config" / "config.yaml").read_text()
    assert str(server) in config and "path\\to" not in config
    assert system.called("firewall") and system.called("shortcuts")
    assert system.called("register_startup")[-1][2] == "boot"
    assert ("api", "PUT", "/servers/survival/color", {"color": "teal"}) in system.calls


def test_a_new_install_with_no_server_yet_keeps_the_java_for_the_first_one(places, program_files):
    choices = Choices(
        action=engine.INSTALL,
        program_dir=places["program"],
        data_root=places["data"],
        password=PASSWORD,
        java_path="/opt/java21/bin/java",
    )
    _, result, _ = run_engine(choices, program_files)
    assert result.ok, result.message + result.details
    from agent.config import Config

    config = Config.load(places["data"] / "config" / "config.yaml")
    # New servers made in the dashboard copy the first entry's Java.
    assert config.server.java == "/opt/java21/bin/java"


def test_a_failed_install_log_names_the_step_and_holds_no_secrets(tmp_path, places, program_files):
    server = make_server(tmp_path)
    system = FakeSystem()

    def refuse(script, port, redirect_port, remove=False):
        from installer.system import SystemError_

        raise SystemError_(
            f"Couldn't open port {port} because another program is using it.",
            f"firewall.ps1 exited 1 while handling {PASSWORD}",
        )

    system.firewall = refuse
    choices = Choices(
        action=engine.INSTALL,
        program_dir=places["program"],
        data_root=places["data"],
        servers=[{"folder": str(server), "name": "Survival"}],
        password=PASSWORD,
    )
    _, result, _ = run_engine(choices, program_files, system)
    assert not result.ok and result.failed_step == "firewall"
    assert "another program is using it" in result.message
    text = Path(result.log_path).read_text()
    events = [json.loads(line) for line in text.splitlines()]
    failed = [e for e in events if e["event"] == "step_failed"]
    assert failed and failed[0]["step"] == "firewall"
    assert "exited 1" in failed[0]["error"]
    env = (places["data"] / "config" / ".env").read_text()
    password_hash = next(
        line.split("=", 1)[1] for line in env.splitlines() if line.startswith("MCSC_ADMIN_PASSWORD")
    )
    token = next(line.split("=", 1)[1] for line in env.splitlines() if line.startswith("MCSC_API"))
    for secret in (PASSWORD, password_hash, token):
        assert secret not in text
    assert PASSWORD not in result.details


def test_install_logs_keep_the_last_few(tmp_path):
    from installer.installlog import InstallLog

    for _ in range(layout.KEEP_INSTALL_LOGS + 3):
        InstallLog(tmp_path).write("x")
    assert len(list(tmp_path.glob("install-*.log"))) == layout.KEEP_INSTALL_LOGS


# ====================================================================
# the progress bar never lies
# ====================================================================
def test_progress_moves_only_for_finished_or_measured_work():
    progress = Progress()
    progress.add("a", "Copying", 30)
    progress.add("b", "Checking", 10)
    assert progress.snapshot()["percent"] == 0
    progress.start("a")
    snap = progress.snapshot()
    assert snap["indeterminate"] and snap["current"] == "Copying" and snap["percent"] == 0
    progress.advance("a", 50, 100)
    snap = progress.snapshot()
    assert not snap["indeterminate"] and snap["percent"] == pytest.approx(37.5)
    progress.finish("a")
    progress.start("b")
    snap = progress.snapshot()
    assert snap["percent"] == 75 and snap["indeterminate"] and snap["current"] == "Checking"
    progress.fail("b", "It didn't answer.")
    with pytest.raises(RuntimeError):
        progress.complete()  # never "Done" after a failure
    assert not progress.snapshot()["finished"]


def test_done_appears_only_after_every_step_passed():
    progress = Progress()
    progress.add("a", "A", 1)
    with pytest.raises(RuntimeError):
        progress.complete()
    progress.start("a")
    progress.finish("a")
    progress.complete()
    assert progress.snapshot() | {} and progress.snapshot()["finished"]
    assert progress.snapshot()["percent"] == 100


def test_the_setup_file_checks_every_file_it_unpacks(tmp_path):
    from installer import bootstrap
    from scripts.build_installer import make_payload

    program = tmp_path / "dist" / "MinecraftServerController"
    (program / "agent" / "web").mkdir(parents=True)
    (program / "mcsc.exe").write_bytes(b"MZ program")
    (program / "agent" / "web" / "index.html").write_text("<html>", encoding="utf-8")
    archive, manifest = make_payload(program, tmp_path / "payload")
    listed = json.loads(manifest.read_text(encoding="utf-8"))
    assert sorted(listed["files"]) == ["program/agent/web/index.html", "program/mcsc.exe"]

    unpacked = bootstrap.unpack(archive, listed, tmp_path / "out")
    assert (unpacked / "mcsc.exe").read_bytes() == b"MZ program"

    listed["files"]["program/mcsc.exe"] = "0" * 64
    with pytest.raises(RuntimeError, match="damaged"):
        bootstrap.unpack(archive, listed, tmp_path / "again")


def test_the_setup_file_refuses_paths_outside_its_folder(tmp_path):
    import zipfile

    from installer import bootstrap

    archive = tmp_path / "payload.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(RuntimeError, match="unsafe path"):
        bootstrap.unpack(archive, {"files": {}}, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_a_failed_lock_down_fails_the_password_step_and_rolls_back(
    tmp_path, places, program_files, monkeypatch
):
    monkeypatch.setattr("agent.security.certs._restrict_file", lambda path: "icacls exit 1332")
    server = make_server(tmp_path)
    choices = Choices(
        action=engine.INSTALL,
        program_dir=places["program"],
        data_root=places["data"],
        servers=[{"folder": str(server), "name": "Survival", "color": "teal"}],
        password=PASSWORD,
        java_path="/opt/java/bin/java",
    )
    _, result, _ = run_engine(choices, program_files)
    assert not result.ok
    assert result.failed_step == "password"
    assert "couldn't be made private" in result.message and "administrator" in result.message
    assert "icacls exit 1332" in result.details


# ====================================================================
# audit fixes
# ====================================================================
def test_an_update_failing_before_the_new_program_is_in_place_starts_the_old_one_again(
    places, program_files, monkeypatch
):
    """Copying the new program can fail (a full disk, a file held open by
    antivirus) after the app and its servers were stopped. They come back."""
    found = make_installer_copy(places, "1.0.0")
    system = FakeSystem()
    system.running = True
    system.servers = [{"id": "s0", "name": "S0", "state": "running"}]

    def full_disk(pairs, report=None):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fileops, "copy_files", full_disk)
    choices = Choices(
        action=engine.UPDATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, system = run_engine(choices, program_files, system=system)
    assert not result.ok and result.failed_step == "program"
    assert result.rolled_back is True, result.rollback_detail
    assert "started the previous version again" in result.rollback_detail
    assert system.called("start_agent")
    assert ("api", "POST", "/servers/s0/server/start", None) in system.calls
    assert (places["program"] / "MinecraftServerController.exe").read_bytes() == b"old agent"


def test_servers_stopped_before_the_app_refused_to_stop_are_started_again(places, program_files):
    found = make_installer_copy(places, "1.0.0")
    system = FakeSystem()
    system.running = True
    system.servers = [{"id": "s0", "name": "S0", "state": "running"}]
    system.stop_agent = lambda port, tls: False
    choices = Choices(
        action=engine.UPDATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, system = run_engine(choices, program_files, system=system)
    assert not result.ok and result.failed_step == "stop"
    assert result.rolled_back is True
    assert ("api", "POST", "/servers/s0/server/start", None) in system.calls


def test_a_moved_copy_keeps_relative_server_folders_pointing_where_they_did(
    tmp_path, places, program_files
):
    project = make_setup_ps1_install(tmp_path, places["data"])
    inside = project / "servers" / "survival"
    inside.mkdir(parents=True)
    (inside / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    config = project / "config" / "config.yaml"
    text = config.read_text(encoding="utf-8")
    one = str(tmp_path / "One")
    config.write_text(text.replace(f"'{one}'", "'servers/survival'"), encoding="utf-8")
    found = detect.classify(project)
    choices = Choices(
        action=engine.MIGRATE, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, _ = run_engine(choices, program_files)
    assert result.ok, result.message + result.details
    from agent.config import Config

    moved = Config.load(
        places["data"] / "config" / "config.yaml", places["data"] / "config" / ".env"
    )
    assert moved.for_server("one").server_dir == inside.resolve()
    assert moved.for_server("two").server_dir == tmp_path / "Two"


def test_an_update_started_by_the_app_unpacks_next_to_the_program_folder(tmp_path):
    from installer import apply_update, bootstrap

    program = tmp_path / "Program Files" / layout.PRODUCT
    staged = apply_update.staging_dir(program) / "MinecraftServerController-Setup-1.2.1.exe"
    assert bootstrap.unpack_parent(staged) == staged.parent
    downloaded = tmp_path / "Downloads" / "MinecraftServerController-Setup-1.2.1.exe"
    assert bootstrap.unpack_parent(downloaded) is None


def test_removing_data_never_removes_a_server_folder_inside_it(places):
    from installer import uninstall

    make_installer_copy(places, "1.2.0", servers=1)
    server = places["data"] / "s0"
    server.mkdir()
    (server / "level.dat").write_bytes(b"world")
    staging = places["program"].with_name(places["program"].name + ".update")
    staging.mkdir()
    result = uninstall.uninstall(
        places["program"], places["data"], remove_data=True, system=FakeSystem()
    )
    assert (server / "level.dat").read_bytes() == b"world"
    assert any("holds a Minecraft server folder" in p for p in result["problems"])
    assert not places["program"].exists() and not staging.exists()

    (places["data"] / "config" / "config.yaml").write_text(
        f"paths:\n  data_dir: '{places['data']}'\nservers:\n"
        f"  - id: s0\n    name: S0\n    directory: '{places['data'].parent / 'elsewhere'}'\n",
        encoding="utf-8",
    )
    result = uninstall.uninstall(
        places["program"], places["data"], remove_data=True, system=FakeSystem()
    )
    assert not places["data"].exists(), result


# ====================================================================
# the address the app listens on
# ====================================================================
@pytest.mark.parametrize(
    "network_host, contacted",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("0.0.0.0", "127.0.0.1"),
        ("::", "127.0.0.1"),
        ("localhost", "127.0.0.1"),
        ("100.101.102.103", "100.101.102.103"),
        ("fd7a:115c:a1e0::1", "[fd7a:115c:a1e0::1]"),
    ],
)
def test_the_installer_reaches_the_app_where_it_listens(network_host, contacted):
    from installer.system import contact_host

    assert contact_host(network_host) == contacted


def new_install(places, **choices):
    return Choices(
        action=engine.INSTALL,
        program_dir=places["program"],
        data_root=places["data"],
        password=PASSWORD,
        **choices,
    )


def test_a_new_install_without_tailscale_names_an_address_that_answers(places, program_files):
    from agent.config import Config

    _, result, system = run_engine(new_install(places), program_files)
    assert result.ok, result.message + result.details
    config = Config.load(places["data"] / "config" / "config.yaml")
    assert config.network.host == "127.0.0.1"
    # The PC's own name isn't where it listens, so the address is localhost.
    assert result.dashboard_url == f"https://localhost:{config.network.port}"
    assert set(system.hosts_asked) == {"127.0.0.1"}


def test_a_new_install_with_tailscale_listens_on_its_address(places, program_files):
    from agent.config import Config

    system = FakeSystem()
    system.tailscale = "100.101.102.103"
    _, result, _ = run_engine(new_install(places), program_files, system)
    assert result.ok, result.message + result.details
    config = Config.load(places["data"] / "config" / "config.yaml")
    assert config.network.host == "100.101.102.103"
    assert system.hosts_asked and set(system.hosts_asked) == {"100.101.102.103"}
    assert result.dashboard_url == config.base_url


def test_a_new_install_for_this_pc_only_stays_on_127_0_0_1(places, program_files):
    from agent.config import Config

    system = FakeSystem()
    system.tailscale = "100.101.102.103"
    _, result, _ = run_engine(new_install(places, allow_devices=False), program_files, system)
    assert result.ok, result.message + result.details
    config = Config.load(places["data"] / "config" / "config.yaml")
    assert config.network.host == "127.0.0.1"


def test_an_update_reaches_an_app_on_its_tailscale_address(places, program_files):
    found = make_installer_copy(places)
    config_file = places["data"] / "config" / "config.yaml"
    config_file.write_text(
        config_file.read_text(encoding="utf-8") + "network:\n  host: 100.101.102.103\n",
        encoding="utf-8",
    )
    action, _ = engine.decide_action(found, "1.2.0")
    system = FakeSystem()
    system.running = True
    choices = Choices(
        action=action, program_dir=places["program"], data_root=places["data"], found=found
    )
    _, result, _ = run_engine(choices, program_files, system)
    assert result.ok, result.message + result.details
    assert system.hosts_asked and set(system.hosts_asked) == {"100.101.102.103"}
