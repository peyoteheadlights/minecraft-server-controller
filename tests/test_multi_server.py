"""Several servers in one agent: config, isolation, API, live updates."""

import asyncio
import sqlite3

import pytest
import yaml

from agent.config import Config, ConfigError, check_server_id
from agent.core import AgentCore, UnknownServer
from agent.database.db import Database
from agent.events import Event
from agent.minecraft.process import ServerError
from agent.minecraft.state import ServerState

from .conftest import PASSWORD, build_multi_config, fake_server_entry, make_server_folder
from .test_mods import make_jar


@pytest.fixture
def multi(tmp_path):
    return build_multi_config(tmp_path)


@pytest.fixture
def multi_client(multi, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    with TestClient(create_app(multi)) as client:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


async def wait_for(predicate, timeout=15.0):
    for _ in range(int(timeout / 0.1)):
        if predicate():
            return True
        await asyncio.sleep(0.1)
    return predicate()


# ------------------------------------------------------------------ config
def test_a_lone_server_block_is_a_one_item_list(config):
    assert config.server_ids == ["test"]
    assert config.default_server_id == "test"
    assert config.for_server("test").server.name == "Test Server"


def test_a_lone_server_block_is_saved_back_the_same_way(config, tmp_path):
    config.set("server.max_players", 30)
    saved = yaml.safe_load(config.save().read_text(encoding="utf-8"))
    assert "server" in saved and "servers" not in saved
    assert saved["server"]["max_players"] == 30


def test_several_servers_are_saved_as_a_list(multi):
    saved = yaml.safe_load(multi.save().read_text(encoding="utf-8"))
    assert [s["id"] for s in saved["servers"]] == ["survival", "creative"]
    assert "server" not in saved


def test_server_and_servers_together_are_refused(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("server:\n  id: a\nservers:\n  - id: b\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(path)


def test_duplicate_ids_are_refused(tmp_path):
    folder = make_server_folder(tmp_path / "A")
    data = {
        "servers": [fake_server_entry("one", "A", folder), fake_server_entry("ONE", "B", folder)]
    }
    with pytest.raises(ConfigError):
        Config(data, tmp_path / "config.yaml").validate()


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a b", "con", "-x", "x" * 65])
def test_unsafe_server_ids_are_refused(bad):
    with pytest.raises(ConfigError):
        check_server_id(bad)


def test_per_server_overrides(tmp_path):
    cfg = build_multi_config(tmp_path)
    cfg.set_server_value("creative", "backups.keep_daily", 3)
    cfg.set_server_value("creative", "monitor.auto_restart", True)
    assert cfg.for_server("creative").backups.keep_daily == 3
    assert cfg.for_server("creative").monitor.auto_restart is True
    assert cfg.for_server("survival").backups.keep_daily != 3
    assert cfg.for_server("survival").monitor.auto_restart is False


def test_the_server_id_cannot_be_changed(multi):
    with pytest.raises(ConfigError):
        multi.set_server_value("survival", "server.id", "other")


def test_each_server_has_its_own_folders(multi):
    a, b = multi.for_server("survival"), multi.for_server("creative")
    assert a.server_dir != b.server_dir
    assert a.backup_dir != b.backup_dir
    assert a.crash_dir != b.crash_dir
    assert a.mods_dir == a.server_dir / "mods"
    # A fresh data folder: every server under servers/<id>/.
    assert a.data_dir == multi.data_dir / "servers" / "survival"
    assert b.data_dir == multi.data_dir / "servers" / "creative"
    assert multi.database_path == b.database_path  # one shared database


def make_pre_multi_server(config):
    """Make the data folder look like one a single-server agent used: a
    database and no layout.json."""
    (config.data_dir / "layout.json").unlink()
    Database(config.database_path).close()
    config._layout = None


def test_an_existing_data_folder_keeps_its_flat_layout(config):
    # The first server's files stay at the top, as they always were.
    make_pre_multi_server(config)
    assert config.layout()["flat_server"] == "test"
    assert config.for_server("test").backup_dir == config.data_dir / "backups"
    config.ensure_dirs()
    assert '"flat_server": "test"' in (config.data_dir / "layout.json").read_text()


def test_removing_the_last_server_is_refused(config):
    with pytest.raises(ConfigError):
        config.remove_server("test")


# ------------------------------------------------------------------ isolation
async def test_two_servers_run_side_by_side(multi):
    core = AgentCore(multi)
    await core.start()
    try:
        a, b = core.get_server("survival"), core.get_server("creative")
        await a.server.start(actor="tester")
        await b.server.start(actor="tester")
        assert await a.server.wait_online(timeout=15)
        assert await b.server.wait_online(timeout=15)
        assert a.server.pid != b.server.pid
        summaries = {ctx.server_id: ctx.summary() for ctx in core.servers.values()}
        assert summaries["survival"]["state"] == "ONLINE"
        assert summaries["creative"]["state"] == "ONLINE"
        await a.server.stop(actor="tester")
        assert b.server.state is ServerState.ONLINE
    finally:
        await core.stop()


async def test_mods_on_one_server_do_not_appear_on_the_other(multi):
    core = AgentCore(multi)
    try:
        a, b = core.get_server("survival"), core.get_server("creative")
        make_jar(a.config.mods_dir / "sodium.jar", "sodium", "0.5.8")
        assert [m.mod_id for m in a.mods.scan()] == ["sodium"]
        assert b.mods.scan() == []
    finally:
        core.db.close()


async def test_a_crash_on_one_server_does_not_restart_the_other(tmp_path):
    cfg = build_multi_config(tmp_path, **{})
    cfg.set_server_value("survival", "monitor.auto_restart", True)
    cfg.set_server_value("survival", "monitor.restart_delay", 0.2)
    core = AgentCore(cfg)
    seen = []
    core.bus.subscribe(lambda e: seen.append(e))
    await core.start()
    try:
        a, b = core.get_server("survival"), core.get_server("creative")
        await a.server.start()
        await b.server.start()
        assert await a.server.wait_online(timeout=15)
        assert await b.server.wait_online(timeout=15)
        b_pid = b.server.pid
        await a.server.send_command("crash")
        assert await wait_for(
            lambda: any(e.type == "server_recovered" and e.server_id == "survival" for e in seen),
            timeout=20,
        ), "\n".join(
            f"{e.type} {e.server_id} {e.message}"
            for e in seen
            if e.type not in ("metrics", "console")
        )
        assert b.server.pid == b_pid
        assert b.server.state is ServerState.ONLINE
        crashes = [e for e in seen if e.type == "server_crashed"]
        assert crashes and all(e.server_id == "survival" for e in crashes)
        # Recorded against the right server.
        rows = core.db.query("SELECT DISTINCT server_id FROM events WHERE type='server_crashed'")
        assert [r["server_id"] for r in rows] == ["survival"]
    finally:
        await core.stop()


async def test_every_event_carries_its_server(multi):
    core = AgentCore(multi)
    seen = []
    core.bus.subscribe(lambda e: seen.append(e))
    try:
        await core.get_server("creative").bus.publish(Event(type="test_event", message="hi"))
        assert seen[-1].server_id == "creative"
        assert seen[-1].to_dict()["server_id"] == "creative"
    finally:
        core.db.close()


async def test_a_server_refuses_to_start_on_a_port_another_running_server_uses(tmp_path):
    cfg = build_multi_config(
        tmp_path, servers=[("survival", "Survival", 25565), ("copy", "Copy", 25565)]
    )
    core = AgentCore(cfg)
    await core.start()
    try:
        a, b = core.get_server("survival"), core.get_server("copy")
        await a.server.start()
        assert await a.server.wait_online(timeout=15)
        with pytest.raises(ServerError) as info:
            await b.server.start()
        assert "Survival" in str(info.value)
        assert "25565" in str(info.value)
    finally:
        await core.stop()


async def test_a_server_refuses_to_start_in_a_folder_another_running_server_uses(tmp_path):
    folder = make_server_folder(tmp_path / "Shared")
    nested = make_server_folder(folder / "inner", 25570)
    data = {
        "servers": [
            fake_server_entry("outer", "Outer", folder, 25565),
            fake_server_entry("inner", "Inner", nested, 25570),
        ],
        "paths": {"data_dir": str(tmp_path / "data")},
        "monitor": {"auto_restart": False},
        "notifications": {"discord_enabled": False, "email_enabled": False},
    }
    core = AgentCore(Config(data, tmp_path / "config.yaml"))
    await core.start()
    try:
        await core.get_server("outer").server.start()
        assert await core.get_server("outer").server.wait_online(timeout=15)
        with pytest.raises(ServerError) as info:
            await core.get_server("inner").server.start()
        assert "Outer" in str(info.value)
    finally:
        await core.stop()


async def test_unknown_server_id(multi):
    core = AgentCore(multi)
    try:
        with pytest.raises(UnknownServer):
            core.get_server("nope")
    finally:
        core.db.close()


# ------------------------------------------------------------------ upgrade
def test_an_old_single_server_database_upgrades_cleanly(tmp_path):
    """A database written before multi-server (schema 2) gains the new
    tables and copies its one server's settings to that server."""
    from agent.database.db import MIGRATIONS

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    for version, script in MIGRATIONS:
        if version > 2:
            break
        conn.executescript(script)
        conn.execute("INSERT INTO schema_version VALUES (?, 0)", (version,))
    conn.execute(
        "INSERT INTO servers (id, name, directory, created_at) VALUES ('test', 'T', '/x', 0)"
    )
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('tps.provider', '\"spark\"', 0)"
    )
    conn.execute(
        "INSERT INTO audit_log (ts, user, action, result) VALUES (0, 'admin', 'login', 'ok')"
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        assert db.version == MIGRATIONS[-1][0]
        assert db.query("SELECT * FROM jobs") == []
        settings = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings")}
        assert settings["server:test:tps.provider"] == settings["tps.provider"]
        audit = db.query("SELECT action, server_id FROM audit_log")
        assert audit == [{"action": "login", "server_id": None}]
        assert db.query_one("PRAGMA integrity_check")["integrity_check"] == "ok"
    finally:
        db.close()


async def test_an_old_single_server_install_starts_unchanged(config):
    make_pre_multi_server(config)
    core = AgentCore(config)
    await core.start()
    try:
        assert list(core.servers) == ["test"]
        assert core.server is core.default.server
        assert core.config.for_server("test").backup_dir == config.data_dir / "backups"
    finally:
        await core.stop()


# ------------------------------------------------------------------ API
def test_per_server_routes_and_old_aliases(multi_client):
    a = multi_client.get("/api/servers/survival/status")
    b = multi_client.get("/api/servers/creative/status")
    assert a.status_code == b.status_code == 200
    assert a.json()["directory"] != b.json()["directory"]
    old = multi_client.get("/api/status")
    assert old.status_code == 200
    assert old.json()["directory"] == a.json()["directory"]  # the first server
    assert old.headers.get("Deprecation")
    assert "Deprecation" not in a.headers


def test_unknown_server_is_404(multi_client):
    response = multi_client.get("/api/servers/nope/status")
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


@pytest.mark.parametrize(
    "path",
    ["mods", "backups", "players", "performance", "schedules", "crashes", "worlds", "logs"],
)
def test_every_area_is_served_per_server(multi_client, path):
    assert multi_client.get(f"/api/servers/creative/{path}").status_code == 200


def test_mods_api_is_per_server(multi_client, multi):
    make_jar(multi.for_server("creative").mods_dir / "lithium.jar", "lithium")
    creative = multi_client.get("/api/servers/creative/mods").json()
    survival = multi_client.get("/api/servers/survival/mods").json()
    assert [m["mod_id"] for m in creative["mods"]] == ["lithium"]
    assert survival["mods"] == []


def test_server_list(multi_client):
    body = multi_client.get("/api/servers").json()
    assert [s["id"] for s in body["servers"]] == ["survival", "creative"]
    assert body["default"] == "survival"
    for row in body["servers"]:
        assert row["state"] in ("OFFLINE", "UNKNOWN")
        assert row["players_online"] in (0, None)  # verified zero or unknown, never a guess


def test_add_and_remove_a_server(multi_client, multi, tmp_path):
    folder = make_server_folder(tmp_path / "Skyblock", 25567)
    response = multi_client.post(
        "/api/servers", json={"name": "Skyblock", "directory": str(folder)}
    )
    assert response.status_code == 200, response.text
    server = response.json()["server"]
    assert server["id"] == "skyblock"
    assert multi_client.get("/api/servers/skyblock/status").status_code == 200
    saved = yaml.safe_load(multi.source.read_text(encoding="utf-8"))
    entry = next(s for s in saved["servers"] if s["id"] == "skyblock")
    assert entry["directory"] == str(folder.resolve())
    assert "raw_command" not in entry

    removed = multi_client.delete("/api/servers/skyblock")
    assert removed.status_code == 200
    assert multi_client.get("/api/servers/skyblock/status").status_code == 404
    # Removing only unregisters: the folder and its world are still there.
    assert (folder / "world" / "level.dat").is_file()
    assert (folder / "fabric-server-launch.jar").is_file()


@pytest.mark.parametrize(
    "directory",
    ["relative/folder", "", "/definitely/not/here"],
)
def test_adding_a_bad_folder_is_refused(multi_client, directory):
    response = multi_client.post("/api/servers", json={"name": "X", "directory": directory or " "})
    assert response.status_code in (400, 422)


def test_adding_a_folder_another_server_uses_is_refused(multi_client, multi):
    folder = multi.for_server("survival").server_dir
    response = multi_client.post("/api/servers", json={"name": "Again", "directory": str(folder)})
    assert response.status_code == 400
    assert "Survival" in response.json()["detail"]


def test_adding_the_agent_folder_is_refused(multi_client, multi):
    response = multi_client.post(
        "/api/servers", json={"name": "Data", "directory": str(multi.data_dir)}
    )
    assert response.status_code == 400


def test_a_running_server_cannot_be_removed(multi_client):
    assert multi_client.post("/api/servers/creative/server/start").status_code == 200
    try:
        response = multi_client.delete("/api/servers/creative")
        assert response.status_code == 409
        assert "Stop Creative" in response.json()["detail"]
    finally:
        multi_client.post("/api/servers/creative/server/stop")


def test_per_server_settings(multi_client, multi):
    response = multi_client.put(
        "/api/servers/creative/settings", json={"updates": {"backups.keep_daily": 4}}
    )
    assert response.status_code == 200, response.text
    assert multi.for_server("creative").backups.keep_daily == 4
    assert multi.for_server("survival").backups.keep_daily != 4
    body = multi_client.get("/api/servers/creative/settings").json()
    assert body["backups"]["keep_daily"] == 4
    assert body["overrides"]["backups"] == {"keep_daily": 4}


def test_websocket_ready_lists_servers_and_tags_events(multi_client):
    token = multi_client.headers["Authorization"].split()[1]
    with multi_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token, "server_id": "creative"})
        ready = ws.receive_json()
        while ready.get("type") != "ready":
            ready = ws.receive_json()
        assert ready["server_id"] == "creative"
        assert [s["id"] for s in ready["servers"]] == ["survival", "creative"]


def test_saving_keeps_the_config_as_you_wrote_it(config):
    from agent.config import BACKUP_SUFFIX, ORIGINAL_SUFFIX

    source = config.save()
    source.with_name(source.name + ORIGINAL_SUFFIX).unlink(missing_ok=True)
    source.write_text("# my notes\n" + source.read_text(encoding="utf-8"), encoding="utf-8")
    written = source.read_text(encoding="utf-8")
    config.save()
    config.save()
    original = source.with_name(source.name + ORIGINAL_SUFFIX)
    assert original.read_text(encoding="utf-8") == written  # comments and all
    previous = source.with_name(source.name + BACKUP_SUFFIX)
    assert previous.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
