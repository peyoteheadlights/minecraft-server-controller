import hashlib
import json
import zipfile

import httpx
import pytest

from agent import downloads
from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.process import MinecraftServer
from agent.mods.jarinfo import read_mod_jar, version_satisfies
from agent.mods.manager import ModError, ModManager
from agent.mods.modrinth import ModrinthClient, ModrinthError
from agent.security.paths import PathSafetyError


def make_jar(path, mod_id, version="1.0.0", depends=None, breaks=None, name=None, loader="fabric"):
    """Write a minimal but realistic mod jar."""
    meta = {
        "schemaVersion": 1,
        "id": mod_id,
        "version": version,
        "name": name or mod_id.title(),
        "description": f"Test mod {mod_id}",
        "authors": ["tester"],
        "environment": "*",
        "depends": depends or {},
    }
    if breaks:
        meta["breaks"] = breaks
    with zipfile.ZipFile(path, "w") as zf:
        if loader == "fabric":
            zf.writestr("fabric.mod.json", json.dumps(meta))
        elif loader == "forge":
            zf.writestr("META-INF/mods.toml", "modLoader='javafml'")
        else:
            zf.writestr("readme.txt", "not a mod")
        zf.writestr(f"{mod_id}/Main.class", b"\xca\xfe\xba\xbe")
    return path


@pytest.fixture
def manager(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    server.mc_version = "1.20.1"
    server.loader_version = "0.16.5"
    return ModManager(config, bus, db, server)


# ---------------------------------------------------------------- reading
def test_scan_reads_fabric_metadata(manager, config):
    make_jar(config.mods_dir / "sodium.jar", "sodium", "0.5.8")
    mods = manager.scan()
    assert len(mods) == 1
    assert mods[0].mod_id == "sodium"
    assert mods[0].version == "0.5.8"
    assert mods[0].enabled is True
    assert mods[0].sha256


def test_jars_for_another_loader_are_flagged(manager, config):
    """A Forge mod reads as a Forge mod, and the check against this
    server's type (Fabric) is what reports it as wrong."""
    make_jar(config.mods_dir / "forgemod.jar", "forgemod", loader="forge")
    make_jar(config.mods_dir / "mystery.jar", "mystery", loader="none")
    found = {m.filename: m for m in manager.scan()}
    assert found["forgemod.jar"].loader == "forge"
    assert found["mystery.jar"].loader == "unknown"
    assert found["mystery.jar"].problems

    per_mod = {m["filename"]: m for m in manager.check_all()["per_mod"]}
    issues = [i["detail"] for i in per_mod["forgemod.jar"]["issues"]]
    assert any("Forge" in detail and "Fabric" in detail for detail in issues)
    assert per_mod["forgemod.jar"]["status"] == "error"


def test_corrupt_jar_does_not_raise(manager, config):
    (config.mods_dir / "broken.jar").write_bytes(b"this is not a zip file")
    mods = manager.scan()
    assert mods[0].problems


# ---------------------------------------------------------------- checks
def test_missing_dependency_is_reported(manager, config):
    make_jar(
        config.mods_dir / "needy.jar",
        "needy",
        "1.0.0",
        depends={"fabric-api": ">=0.90.0", "minecraft": ">=1.20"},
    )
    problems = manager.check_all()["problems"]
    kinds = {p["kind"] for p in problems}
    assert "missing_dependency" in kinds
    detail = next(p["detail"] for p in problems if p["kind"] == "missing_dependency")
    assert "Fabric API" in detail  # a readable name, not the raw id
    assert "0.90.0 or newer" in detail  # the range in words, not ">=0.90.0"
    assert ">=" not in detail


def test_satisfied_dependency_is_not_reported(manager, config):
    make_jar(config.mods_dir / "needy.jar", "needy", depends={"fabric-api": ">=0.90.0"})
    make_jar(config.mods_dir / "fabric-api.jar", "fabric-api", "0.92.0")
    assert not manager.check_all()["problems"]


def test_dependency_version_mismatch_is_reported(manager, config):
    make_jar(config.mods_dir / "needy.jar", "needy", depends={"fabric-api": ">=0.95.0"})
    make_jar(config.mods_dir / "fabric-api.jar", "fabric-api", "0.90.0")
    problems = manager.check_all()["problems"]
    assert any(p["kind"] == "dependency_version" for p in problems)


def test_duplicate_mod_ids_are_reported(manager, config):
    make_jar(config.mods_dir / "sodium-a.jar", "sodium", "0.5.8")
    make_jar(config.mods_dir / "sodium-b.jar", "sodium", "0.5.9")
    problems = manager.check_all()["problems"]
    assert any(p["kind"] == "duplicate_mod_id" for p in problems)


def test_declared_incompatibility_is_reported(manager, config):
    make_jar(config.mods_dir / "a.jar", "moda", "1.0.0", breaks={"modb": "*"})
    make_jar(config.mods_dir / "b.jar", "modb", "1.0.0")
    problems = manager.check_all()["problems"]
    assert any(p["kind"] == "known_incompatibility" for p in problems)


def test_checker_states_its_limitations(manager):
    limitations = manager.check_all()["limitations"]
    assert any("clash" in text for text in limitations)
    assert any("fabric.mod.json" in text for text in limitations), (
        "the limits must name the file this type's metadata is read from"
    )


def test_unverifiable_version_range_is_not_claimed_as_pass():
    assert version_satisfies("1.0.0", ">=0.9") is True
    assert version_satisfies("1.0.0", ">=2.0") is False
    assert version_satisfies("1.0.0", "[1.0,2.0)") is None  # Maven range: not modelled


# ---------------------------------------------------------------- writes
async def test_enable_and_disable_renames_the_jar(manager, config):
    make_jar(config.mods_dir / "sodium.jar", "sodium")
    await manager.set_enabled("sodium.jar", False, user="tester")
    assert (config.mods_dir / "sodium.jar.disabled").is_file()
    assert not (config.mods_dir / "sodium.jar").exists()
    assert manager.scan()[0].enabled is False
    await manager.set_enabled("sodium.jar.disabled", True, user="tester")
    assert (config.mods_dir / "sodium.jar").is_file()


async def test_remove_archives_and_trashes_instead_of_deleting(manager, config):
    make_jar(config.mods_dir / "sodium.jar", "sodium", "0.5.8")
    result = await manager.remove("sodium.jar", user="tester")
    assert not (config.mods_dir / "sodium.jar").exists()
    assert list(config.mod_trash_dir.iterdir()), "the jar should be in the trash folder"
    assert result["archived"] and list((config.mod_backup_dir / "sodium").iterdir())
    history = manager.history()
    assert history[0]["action"] == "remove"
    assert history[0]["user"] == "tester"


async def test_removal_impact_warns_about_dependents(manager, config):
    make_jar(config.mods_dir / "fabric-api.jar", "fabric-api", "0.92.0")
    make_jar(config.mods_dir / "needy.jar", "needy", depends={"fabric-api": ">=0.9"})
    impact = manager.removal_impact("fabric-api.jar")
    assert impact["warning"]
    assert impact["dependents"][0]["mod_id"] == "needy"


async def test_mod_writes_are_refused_while_the_server_runs(manager, config):
    make_jar(config.mods_dir / "sodium.jar", "sodium")
    await manager.server.start()
    await manager.server.wait_online(timeout=15)
    try:
        with pytest.raises(ModError, match="Stop it before"):
            await manager.remove("sodium.jar", user="tester")
    finally:
        await manager.server.stop()


async def test_upload_refuses_non_jar_content(manager):
    with pytest.raises(ModError):
        await manager.install_local_file("evil.jar", b"MZ this is an executable", user="tester")


async def test_upload_refuses_executable_filenames(manager):
    with pytest.raises(PathSafetyError):
        await manager.install_local_file("payload.exe", b"PK\x03\x04", user="tester")


async def test_upload_refuses_path_traversal(manager):
    with pytest.raises(PathSafetyError):
        await manager.install_local_file("../../evil.jar", b"PK\x03\x04", user="tester")


async def test_upload_installs_a_valid_fabric_jar(manager, config, tmp_path):
    source = make_jar(tmp_path / "build.jar", "cooltech", "2.1.0")
    result = await manager.install_local_file(
        "cooltech-2.1.0.jar", source.read_bytes(), user="tester"
    )
    assert result["installed"]["mod_id"] == "cooltech"
    assert (config.mods_dir / "cooltech-2.1.0.jar").is_file()


async def test_upload_does_not_silently_overwrite(manager, config, tmp_path):
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0")
    source = make_jar(tmp_path / "new.jar", "cooltech", "2.0.0")
    with pytest.raises(ModError, match="already there"):
        await manager.install_local_file("cooltech.jar", source.read_bytes(), user="tester")


async def test_rollback_restores_an_archived_version(manager, config, tmp_path):
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0")
    old = read_mod_jar(config.mods_dir / "cooltech.jar")
    archive = manager.archive(config.mods_dir / "cooltech.jar", old, source="test")
    # replace with a newer build
    (config.mods_dir / "cooltech.jar").unlink()
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "2.0.0")
    assert manager.find_by_id("cooltech").version == "2.0.0"

    result = await manager.rollback("cooltech", str(archive), user="tester")
    assert result["restored"]["version"] == "1.0.0"
    assert result["previous_version"] == "2.0.0"


async def test_rollback_refuses_a_tampered_archive(manager, config):
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0")
    info = read_mod_jar(config.mods_dir / "cooltech.jar")
    archive = manager.archive(config.mods_dir / "cooltech.jar", info, source="test")
    archive.write_bytes(b"PK\x03\x04tampered")
    with pytest.raises(ModError, match="changed since it was saved"):
        await manager.rollback("cooltech", str(archive), user="tester")


async def test_rollback_refuses_paths_outside_the_backup_folder(manager, config, tmp_path):
    outside = tmp_path / "elsewhere.jar"
    make_jar(outside, "cooltech")
    with pytest.raises(ModError):
        await manager.rollback("cooltech", str(outside), user="tester")


# ---------------------------------------------------------------- downloads
@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """The safe downloader always goes through a fake network in tests, so
    nothing can leave the machine."""

    def refuse(request):
        raise AssertionError(f"unexpected request to {request.url}")

    monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(refuse))


def modrinth_with_transport(config, handler, monkeypatch=None):
    client = ModrinthClient(config)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    if monkeypatch is not None:
        monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(handler))
    return client


async def test_download_verifies_the_published_checksum(config, monkeypatch):
    payload = b"PK\x03\x04" + b"jar contents"
    version = {
        "file": {
            "filename": "sodium-0.5.8.jar",
            "url": "https://cdn.modrinth.com/data/AAA/versions/BBB/sodium-0.5.8.jar",
            "size": len(payload),
            "sha1": hashlib.sha1(payload).hexdigest(),
            "sha512": hashlib.sha512(payload).hexdigest(),
        }
    }
    client = modrinth_with_transport(
        config, lambda request: httpx.Response(200, content=payload), monkeypatch
    )
    data, filename, digest = await client.download(version)
    assert data == payload
    assert filename == "sodium-0.5.8.jar"
    assert digest == hashlib.sha256(payload).hexdigest()
    await client.close()


async def test_download_refuses_a_checksum_mismatch(config, monkeypatch):
    version = {
        "file": {
            "filename": "x.jar",
            "url": "https://cdn.modrinth.com/data/A/versions/B/x.jar",
            "sha512": hashlib.sha512(b"expected").hexdigest(),
        }
    }
    client = modrinth_with_transport(
        config, lambda request: httpx.Response(200, content=b"PK\x03\x04different"), monkeypatch
    )
    with pytest.raises(ModrinthError, match="checksum"):
        await client.download(version)
    await client.close()


async def test_download_refuses_a_file_with_no_checksum(config, monkeypatch):
    version = {
        "file": {"filename": "x.jar", "url": "https://cdn.modrinth.com/data/A/versions/B/x.jar"}
    }
    client = modrinth_with_transport(
        config, lambda request: httpx.Response(200, content=b"PK\x03\x04"), monkeypatch
    )
    with pytest.raises(ModrinthError, match="no checksum"):
        await client.download(version)
    await client.close()


@pytest.mark.parametrize(
    "url,filename",
    [
        ("https://evil.example.com/sodium.jar", "sodium.jar"),  # wrong host
        ("http://cdn.modrinth.com/sodium.jar", "sodium.jar"),  # not https
        ("https://cdn.modrinth.com/payload.exe", "payload.exe"),  # executable
        ("https://cdn.modrinth.com/../escape.jar", "../escape.jar"),  # traversal
    ],
)
async def test_download_refuses_unsafe_sources(config, monkeypatch, url, filename):
    version = {"file": {"filename": filename, "url": url, "sha512": "x" * 128}}
    client = modrinth_with_transport(
        config, lambda request: httpx.Response(200, content=b"PK"), monkeypatch
    )
    with pytest.raises(ModrinthError):
        await client.download(version)
    await client.close()


async def test_download_refuses_content_that_is_not_an_archive(config, monkeypatch):
    payload = b"MZ windows executable"
    version = {
        "file": {
            "filename": "x.jar",
            "url": "https://cdn.modrinth.com/data/A/versions/B/x.jar",
            "sha512": hashlib.sha512(payload).hexdigest(),
        }
    }
    client = modrinth_with_transport(
        config, lambda request: httpx.Response(200, content=payload), monkeypatch
    )
    with pytest.raises(ModrinthError, match="isn't a mod"):
        await client.download(version)
    await client.close()
