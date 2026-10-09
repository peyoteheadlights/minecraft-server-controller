"""Phase 6: world import and download, off-PC backup copies, the memory
limit, keeping the PC awake, Move to a new PC, and Get help."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from agent import helpbundle, memory, transfer, worldimport
from agent.backups import offsite
from agent.backups.manager import BackupManager
from agent.database.db import Database
from agent.events import EventBus
from agent.keepawake import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, KeepAwake
from agent.minecraft import nbt
from agent.minecraft.process import MinecraftServer

from .conftest import PASSWORD


def level_dat(name="My World", version="1.21.1") -> bytes:
    return nbt.write_for_tests(
        {"LevelName": name, "Version": {"Name": version}, "LastPlayed": 1_750_000_000_000}
    )


def world_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# ------------------------------------------------------------------ level.dat
def test_level_dat_is_read_for_name_and_version():
    info = nbt.level_info(level_dat())
    assert info["name"] == "My World"
    assert info["version"] == "1.21.1"
    assert info["last_played"] == 1_750_000_000


def test_a_broken_level_dat_is_reported_not_guessed():
    with pytest.raises(nbt.NbtError):
        nbt.level_info(b"\x0a\x00\x00\x01")


# ------------------------------------------------------------------ world import checks
def test_a_zip_without_level_dat_is_refused(tmp_path):
    path = world_zip(tmp_path / "w.zip", {"My World/region/r.0.0.mca": b"x"})
    with pytest.raises(worldimport.WorldImportError, match="level.dat"):
        worldimport.inspect_zip(path)


@pytest.mark.parametrize(
    "evil", ["../evil.txt", "My World/../../evil.txt", "/etc/evil", "C:/Windows/evil.dll"]
)
def test_a_zip_with_zip_slip_paths_is_refused(tmp_path, evil):
    path = world_zip(tmp_path / "w.zip", {"My World/level.dat": level_dat(), evil: b"x"})
    with pytest.raises(worldimport.WorldImportError, match="isn't safe"):
        worldimport.inspect_zip(path)


def test_a_world_zip_shows_name_and_size_first(tmp_path):
    path = world_zip(
        tmp_path / "w.zip",
        {"My World/level.dat": level_dat(), "My World/region/r.0.0.mca": b"x" * 1000},
    )
    info, root = worldimport.inspect_zip(path)
    assert root == "My World"
    assert info.name == "My World" and info.version == "1.21.1"
    assert info.files == 2
    assert info.size_bytes == 1000 + len(level_dat())


def test_two_worlds_in_one_zip_are_refused(tmp_path):
    path = world_zip(tmp_path / "w.zip", {"A/level.dat": level_dat(), "B/level.dat": level_dat()})
    with pytest.raises(worldimport.WorldImportError, match="more than one"):
        worldimport.inspect_zip(path)


def test_a_folder_without_level_dat_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(worldimport.WorldImportError, match="level.dat"):
        worldimport.inspect_folder(str(tmp_path / "empty"))


def test_single_player_dimensions_go_to_paper_folders():
    assert worldimport._target_for("DIM-1/region/r.mca", "world", True) == (
        "world_nether/DIM-1/region/r.mca"
    )
    assert worldimport._target_for("DIM-1/region/r.mca", "world", False) == (
        "world/DIM-1/region/r.mca"
    )
    assert worldimport._target_for("session.lock", "world", False) is None


def test_import_and_download_through_the_api(client, tmp_path):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("Island/level.dat", level_dat("Island"))
        zf.writestr("Island/region/r.0.0.mca", b"chunk" * 100)
    files = {"file": ("island.zip", data.getvalue(), "application/zip")}
    uploaded = client.post("/api/servers/test/world/import/upload", files=files)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["world"]["name"] == "Island"
    upload_token = uploaded.json()["token"]
    # nothing changes without confirming
    refused = client.post("/api/servers/test/world/import", json={"token": upload_token})
    assert refused.status_code == 400
    done = client.post(
        "/api/servers/test/world/import", json={"token": upload_token, "confirm": True}
    )
    assert done.status_code == 200, done.text
    server_dir = client.app.state.core.default.config.server_dir
    assert (server_dir / "world" / "region" / "r.0.0.mca").read_bytes() == b"chunk" * 100
    assert done.json()["undo"], "the old world's backup is the undo"
    assert not list(server_dir.glob("*.replaced-*"))
    packed = client.post("/api/servers/test/world/download")
    assert packed.status_code == 200, packed.text
    body = packed.json()
    got = client.get(f"/api/servers/test/world/download/{body['token']}")
    assert got.status_code == 200
    with zipfile.ZipFile(io.BytesIO(got.content)) as zf:
        assert "world/level.dat" in zf.namelist()


def test_a_bad_zip_upload_changes_nothing(client):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("level.dat", level_dat())
        zf.writestr("../../outside.txt", b"x")
    files = {"file": ("bad.zip", data.getvalue(), "application/zip")}
    response = client.post("/api/servers/test/world/import/upload", files=files)
    assert response.status_code == 400
    uploads = client.app.state.core.config.data_dir / worldimport.UPLOAD_FOLDER
    assert not list(uploads.glob("*.zip"))


# ------------------------------------------------------------------ off-PC copies
@pytest.fixture
def backups(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return BackupManager(config, bus, db, server)


async def test_a_backup_is_copied_off_the_pc_and_checked(backups, config, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    config.set("backups.offsite_directory", str(usb))
    result = await backups.create(user="tester")
    assert result["copy"]["state"] == "ok"
    row = [b for b in backups.list_backups() if b["id"] == result["id"]][0]
    copy = Path(row["copy"]["path"])
    assert copy.read_bytes() == (config.backup_dir / result["name"]).read_bytes()
    assert copy.parent == usb / offsite.SUBFOLDER / "test"


async def test_a_failed_copy_leaves_the_local_backup_intact(backups, config, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    usb.mkdir()
    config.set("backups.offsite_directory", str(usb))

    def broken(*args, **kwargs):
        raise offsite.OffsiteError("drive not connected")

    monkeypatch.setattr(offsite, "copy_file", broken)
    result = await backups.create(user="tester")
    assert (config.backup_dir / result["name"]).is_file()
    assert backups.verify(result["id"])["ok"] is True
    row = [b for b in backups.list_backups() if b["id"] == result["id"]][0]
    assert row["status"] == "ok"
    assert row["copy"] == {"state": "failed", "reason": "drive not connected"}


async def test_an_unplugged_drive_is_reported_as_it_is(backups, config, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    config.set("backups.offsite_directory", str(usb))
    result = await backups.create(user="tester")
    import shutil

    shutil.rmtree(usb)
    row = [b for b in backups.list_backups() if b["id"] == result["id"]][0]
    assert row["status"] == "ok"
    assert row["copy"]["state"] in ("unreachable", "missing")


async def test_retention_removes_the_copy_too(backups, config, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    config.set("backups.offsite_directory", str(usb))
    result = await backups.create(user="tester")
    row = [b for b in backups.list_backups() if b["id"] == result["id"]][0]
    copy = Path(row["copy"]["path"])
    await backups.delete(result["id"], user="tester")
    assert not copy.exists()


def test_the_copy_folder_must_not_overlap_the_server(config):
    with pytest.raises(Exception, match="overlaps"):
        offsite.check_folder(str(config.server_dir), [config.server_dir])


def test_a_copy_that_doesnt_match_is_thrown_away(tmp_path):
    source = tmp_path / "a.zip"
    source.write_bytes(b"backup")
    target = tmp_path / "out" / "a.zip"
    with pytest.raises(offsite.OffsiteError):
        offsite.copy_file(source, target, "0" * 64)
    assert not target.exists() and not list((tmp_path / "out").glob("*.part"))


# ------------------------------------------------------------------ memory
def test_the_limit_replaces_xmx_and_keeps_other_flags():
    args = ["-Xms1G", "-Xmx2G", "-XX:+UseG1GC"]
    assert memory.with_limit(args, 4096) == ["-Xms1G", "-Xmx4G", "-XX:+UseG1GC"]
    assert memory.with_limit(["-XX:+UseG1GC"], 3584) == ["-XX:+UseG1GC", "-Xmx3584M"]


def test_the_memory_warning_uses_measured_ram_only(client, monkeypatch):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    ctx = client.app.state.core.default
    ctx.config.set("server.jvm_args", ["-Xmx6G"])
    monkeypatch.setattr(memory, "total_ram_mb", lambda: 4096)
    assert memory.start_warnings(ctx), "6 GB on a measured 4 GB PC warns"
    assert client.get("/api/servers/test/memory").json()["total_mb"] == 4096
    # RAM that can't be read: no warning, no guessed figure
    monkeypatch.setattr(memory, "total_ram_mb", lambda: None)
    assert memory.start_warnings(ctx) == []
    shown = client.get("/api/servers/test/memory").json()
    assert shown["total_mb"] is None and shown["over"] is False
    refused = client.put("/api/servers/test/memory", json={"memory_mb": 2048})
    assert refused.status_code == 400  # a limit can't be checked against an unknown total


def test_the_memory_slider_saves_xmx(client, monkeypatch):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    monkeypatch.setattr(memory, "total_ram_mb", lambda: 16384)
    ctx = client.app.state.core.default
    ctx.config.set("server.jvm_args", ["-Xms1G", "-Xmx2G", "-XX:+UseG1GC"])
    assert client.put("/api/servers/test/memory", json={"memory_mb": 4096}).status_code == 200
    assert ctx.config.server.jvm_args == ["-Xms1G", "-Xmx4G", "-XX:+UseG1GC"]
    too_much = client.put("/api/servers/test/memory", json={"memory_mb": 32768})
    assert too_much.status_code == 400


# ------------------------------------------------------------------ keep awake
class FakeServer:
    def __init__(self, running):
        self.server = type("S", (), {"running": running})()
        self.name = "fake"


def keep_awake(running, enabled=True):
    calls = []
    core = type("Core", (), {})()
    core.config = type("C", (), {"power": type("P", (), {"keep_awake": enabled})()})()
    core.servers = {"a": FakeServer(running)}

    def call(flags):
        calls.append(flags)
        return 1

    return KeepAwake(core, call=call), core, calls


def test_the_pc_is_kept_awake_only_while_a_server_runs():
    awake, core, calls = keep_awake(True)
    assert awake.update() is True
    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]
    core.servers["a"].server.running = False
    assert awake.update() is False
    assert calls[-1] == ES_CONTINUOUS


def test_keep_awake_can_be_turned_off():
    awake, _, calls = keep_awake(True, enabled=False)
    assert awake.update() is False
    assert calls == []


def test_on_battery_is_reported(monkeypatch):
    from agent import keepawake

    monkeypatch.setattr(
        keepawake, "battery", lambda: {"present": True, "plugged_in": False, "percent": 50}
    )
    monkeypatch.setattr(keepawake, "lid_actions", lambda: None)
    awake, _, _ = keep_awake(True)
    assert "on_battery" in awake.status()["still_sleeps"]


# ------------------------------------------------------------------ export and Get help
SECRET_VALUES = {
    "MCSC_ADMIN_PASSWORD_HASH": "pbkdf2_sha256$1000$c2FsdA==$aGFzaGhhc2hoYXNo",
    "MCSC_API_TOKEN": "api-token-very-secret-123",
    "MCSC_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/1/very-secret-hook",
    "MCSC_SMTP_PASSWORD": "smtp-password-secret-456",
    "MCSC_VAPID_PRIVATE_KEY": "vapid-private-key-secret-789",
}


def everything_in(path: Path) -> str:
    out = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            out.append(name)
            out.append(zf.read(name).decode("utf-8", errors="replace"))
    return "\n".join(out)


@pytest.fixture
def secret_client(client, monkeypatch):
    for key, value in SECRET_VALUES.items():
        if key != "MCSC_ADMIN_PASSWORD_HASH":
            monkeypatch.setenv(key, value)
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    core = client.app.state.core
    (core.default.config.server_dir / "server.properties").write_text(
        "server-port=25565\nrcon.password=rcon-secret-000\n", encoding="utf-8"
    )
    client.post("/api/accounts", json={"username": "sam", "password": "helper password 1"})
    return client


def wait_for_job(client, job_id):
    import time

    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        job = job.get("job", job)
        if job["state"] not in ("running", "queued", "pending"):
            return job
        time.sleep(0.05)
    raise AssertionError("the job never finished")


def export_file(client, **options) -> Path:
    started = client.post("/api/export", json=options)
    assert started.status_code == 200, started.text
    job = wait_for_job(client, started.json()["job_id"])
    assert job["state"] in ("done", "succeeded", "ok"), job
    core = client.app.state.core
    return transfer.folder(core.config) / f"{job['result']['token']}.zip"


def test_an_export_without_secrets_holds_none(secret_client):
    path = export_file(secret_client, worlds=True, backups=False)
    text = everything_in(path)
    for value in [*SECRET_VALUES.values(), "rcon-secret-000", "pbkdf2_sha256"]:
        assert value not in text
    assert "secrets.bin" not in text
    with zipfile.ZipFile(path) as zf:
        assert "servers/test/world/level.dat" in zf.namelist()
        data = json.loads(zf.read("data.json"))
    assert [a["username"] for a in data["accounts"]] == ["sam"]


def test_an_export_without_worlds_leaves_them_out(secret_client):
    with zipfile.ZipFile(export_file(secret_client)) as zf:
        names = zf.namelist()
    assert not any(n.startswith("servers/test/world/") for n in names)
    assert not any("/logs/" in n for n in names)


def test_secrets_are_only_in_the_encrypted_part(secret_client):
    refused = secret_client.post("/api/export", json={"secrets": True, "passphrase": "short"})
    assert refused.status_code == 400
    path = export_file(secret_client, secrets=True, passphrase="a long passphrase")
    text = everything_in(path)
    assert "rcon-secret-000" not in text
    for key, value in SECRET_VALUES.items():
        if key != "MCSC_ADMIN_PASSWORD_HASH":
            assert value not in text
    with zipfile.ZipFile(path) as zf:
        blob = zf.read("secrets.bin")
    with pytest.raises(transfer.TransferError, match="passphrase"):
        transfer.decrypt(blob, "the wrong passphrase")
    opened = transfer.decrypt(blob, "a long passphrase")
    assert opened["env"]["MCSC_API_TOKEN"] == SECRET_VALUES["MCSC_API_TOKEN"]
    assert opened["properties"]["test"]["rcon.password"] == "rcon-secret-000"
    assert "sam" in opened["account_hashes"]


def test_import_on_a_new_pc_relocates_the_servers(secret_client, tmp_path):
    from installer.setup_tool import read_env, write_env_value

    path = export_file(secret_client, worlds=True, secrets=True, passphrase="a long passphrase")
    new_pc = tmp_path / "new-pc"
    new_pc.mkdir()
    env = new_pc / ".env"
    result = transfer.import_all(
        path,
        new_pc / "Servers",
        new_pc / "config" / "config.yaml",
        env,
        passphrase="a long passphrase",
        write_env=write_env_value,
    )
    target = Path(result["servers"][0]["to"])
    assert (target / "world" / "level.dat").is_file()
    assert "rcon.password=rcon-secret-000" in (target / "server.properties").read_text()
    import yaml

    saved = yaml.safe_load((new_pc / "config" / "config.yaml").read_text())
    assert saved["servers"][0]["directory"] == str(target)
    assert read_env(env)["MCSC_API_TOKEN"] == SECRET_VALUES["MCSC_API_TOKEN"]
    assert result["helpers"] == 1
    # a second import into the same folder is refused rather than written over
    with pytest.raises(transfer.TransferError, match="already has files"):
        transfer.plan_import(transfer.read_manifest(path), new_pc / "Servers")


def test_the_help_bundle_holds_no_secrets(secret_client, monkeypatch):
    core = secret_client.app.state.core
    log_dir = Path(core.config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    leaked = " ".join(SECRET_VALUES.values())
    (log_dir / "agent.log").write_text(
        f"INFO started\nWARNING oops {leaked}\nAuthorization: Bearer abcdef123456\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", SECRET_VALUES["MCSC_ADMIN_PASSWORD_HASH"])
    listed = secret_client.get("/api/help-bundle").json()["files"]
    names = [f["name"] for f in listed]
    assert "logs/agent.log" in names and "check-report.txt" in names
    made = secret_client.post("/api/help-bundle", json={"confirm": True})
    assert made.status_code == 200, made.text
    got = secret_client.get(f"/api/help-bundle/{made.json()['token']}")
    assert got.status_code == 200
    with zipfile.ZipFile(io.BytesIO(got.content)) as zf:
        inside = set(zf.namelist())
        text = "\n".join(zf.read(n).decode("utf-8", errors="replace") for n in inside)
    assert set(names) <= inside  # what was listed is what went in
    for value in SECRET_VALUES.values():
        assert value not in text
    assert "abcdef123456" not in text
    assert not any(n.endswith((".env", ".db", ".key", "level.dat", ".mca")) for n in inside)


def test_redaction_cuts_known_shapes():
    text = helpbundle.redact(
        "password=hunter22 https://discord.com/api/webhooks/1/abc pbkdf2_sha256$1$a$b", []
    )
    assert "hunter22" not in text and "webhooks/1/abc" not in text and "pbkdf2" not in text


# ------------------------------------------------------------------ database
def test_migration_adds_accounts_and_copy_columns(tmp_path):
    db = Database(tmp_path / "a.db")
    columns = {r["name"] for r in db.query("PRAGMA table_info(backups)")}
    assert {"copy_path", "copy_status", "copy_detail", "copy_checked_at"} <= columns
    assert db.query("PRAGMA table_info(accounts)")
