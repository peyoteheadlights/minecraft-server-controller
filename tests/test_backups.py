import zipfile

import pytest

from agent.backups.manager import BackupError, BackupManager
from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.process import MinecraftServer


@pytest.fixture
def backups(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return BackupManager(config, bus, db, server)


async def test_create_produces_a_verifiable_archive(backups, config):
    (config.server_dir / "world" / "region.mca").write_bytes(b"chunk data" * 500)
    result = await backups.create(user="tester")
    archive = config.backup_dir / result["name"]
    assert archive.is_file()
    assert result["files"] > 0
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert any(n.startswith("world/") for n in names)
    assert any("server.properties" in n for n in names)
    assert backups.verify(result["id"])["ok"] is True


async def test_verify_detects_a_damaged_archive(backups, config):
    result = await backups.create(user="tester")
    (config.backup_dir / result["name"]).write_bytes(b"corrupted")
    check = backups.verify(result["id"])
    assert check["ok"] is False


async def test_verify_detects_a_missing_archive(backups, config):
    result = await backups.create(user="tester")
    (config.backup_dir / result["name"]).unlink()
    assert backups.verify(result["id"])["ok"] is False


async def test_session_lock_is_skipped(backups, config):
    (config.server_dir / "world" / "session.lock").write_bytes(b"locked")
    result = await backups.create(user="tester")
    with zipfile.ZipFile(config.backup_dir / result["name"]) as zf:
        assert not any("session.lock" in n for n in zf.namelist())


async def test_restore_makes_a_safety_backup_and_puts_files_back(backups, config):
    marker = config.server_dir / "world" / "marker.dat"
    marker.write_text("original world")
    created = await backups.create(user="tester")

    marker.write_text("world changed after the backup")
    result = await backups.restore(created["id"], user="tester")

    assert marker.read_text() == "original world"
    assert result["safety_backup"] is not None
    assert result["safety_backup"]["name"].startswith("safety-")
    # the replaced folder was moved aside, not deleted
    assert any(p.name.startswith("world.replaced-") for p in config.server_dir.iterdir())


async def test_restore_refuses_an_unverifiable_backup(backups, config):
    created = await backups.create(user="tester")
    (config.backup_dir / created["name"]).write_bytes(b"not a zip")
    with pytest.raises(BackupError, match="did not verify"):
        await backups.restore(created["id"], user="tester")


async def test_restore_refuses_an_archive_with_an_escaping_path(backups, config):
    created = await backups.create(user="tester")
    path = config.backup_dir / created["name"]
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("../../escaped.txt", "payload")
    # rewrite the stored hash so the archive verifies and the path check is what fires
    backups.db.execute(
        "UPDATE backups SET sha256 = ? WHERE id = ?", (backups._sha256(path), created["id"])
    )
    with pytest.raises(BackupError):
        await backups.restore(created["id"], user="tester")
    assert not (config.server_dir.parent.parent / "escaped.txt").exists()


async def test_manual_backups_survive_retention(backups, config):
    manual = await backups.create(user="tester", kind="manual")
    for _ in range(3):
        await backups.create(user="tester", kind="scheduled")
    await backups.apply_retention()
    names = [b["name"] for b in backups.list_backups()]
    assert manual["name"] in names


async def test_delete_removes_the_file_and_the_record(backups, config):
    created = await backups.create(user="tester")
    await backups.delete(created["id"], user="tester")
    assert not (config.backup_dir / created["name"]).exists()
    assert created["name"] not in [b["name"] for b in backups.list_backups()]


async def test_world_summary_reports_sizes_and_backup_state(backups, config):
    (config.server_dir / "world" / "region.mca").write_bytes(b"x" * 4096)
    await backups.create(user="tester")
    summary = {w["key"]: w for w in backups.world_summary()}
    assert summary["world"]["exists"] is True
    assert summary["world"]["size_bytes"] > 4000
    assert summary["world"]["last_backup"] is not None


async def test_backup_refuses_when_nothing_to_back_up(backups, config):
    with pytest.raises(BackupError, match="Nothing to back up"):
        await backups.create(user="tester", includes=["no_such_folder"])
