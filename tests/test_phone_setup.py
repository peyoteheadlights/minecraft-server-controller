"""What the phone apps' Setup screens (Phase 9 part 5) need from the agent:
Server settings, version and type changes, the raw editors, new servers,
the PC folder picker and world import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .test_api import auth, token_for

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def signed_in(client):
    client.headers.update(auth(token_for(client)))
    return client


def test_server_settings_say_how_sleep_is_going(signed_in):
    body = signed_in.get("/api/servers/test/settings").json()
    assert body["sleep"]["enabled"] is False
    assert body["sleep"]["minutes"] == 30
    assert [c["id"] for c in body["palette"]]


def test_with_one_server_its_crash_and_backup_settings_stay_app_wide(signed_in, config):
    """Saved from a server's own page, they land where the gear page reads
    them, so the two never show different numbers."""
    response = signed_in.put(
        "/api/servers/test/settings",
        json={"updates": {"monitor.auto_restart": False, "backups.keep_daily": 3}},
    )
    assert response.json()["applied"] == {"monitor.auto_restart": False, "backups.keep_daily": 3}
    assert config.monitor.auto_restart is False
    assert config.backups.keep_daily == 3
    assert not config.server_entry("test").get("monitor")
    body = signed_in.get("/api/servers/test/settings").json()
    assert body["monitor"]["auto_restart"] is False
    assert body["backups"]["keep_daily"] == 3


def test_a_server_with_its_own_value_keeps_it_there(signed_in, config):
    config.set_server_value("test", "backups.keep_daily", 9)
    signed_in.put("/api/servers/test/settings", json={"updates": {"backups.keep_daily": 2}})
    assert config.server_entry("test")["backups"]["keep_daily"] == 2
    assert signed_in.get("/api/servers/test/settings").json()["backups"]["keep_daily"] == 2


def test_a_setting_that_cant_be_changed_says_so_plainly(signed_in):
    body = signed_in.put(
        "/api/servers/test/settings", json={"updates": {"server.java": "x"}}
    ).json()
    assert body["rejected"]["server.java"] == "This setting can't be changed here."
    assert "dashboard" not in body["rejected"]["server.java"]


def test_a_refused_value_comes_back_with_its_reason(signed_in):
    body = signed_in.put(
        "/api/servers/test/settings", json={"updates": {"server.autosleep_minutes": 0}}
    ).json()
    assert body["applied"] == {}
    assert body["rejected"]["server.autosleep_minutes"] == "Pick between 1 minute and 24 hours."


def test_color_answer_is_typed(signed_in):
    body = signed_in.put("/api/servers/test/color", json={"color": "#3366cc"}).json()
    assert body["ok"] is True
    assert body["color"].lower() == "#3366cc"


def test_memory_answer_is_typed_and_bounded_by_the_pc(signed_in):
    body = signed_in.get("/api/servers/test/memory").json()
    assert body["min_mb"] == 1024
    assert body["max_mb"] == body["total_mb"]
    assert body["servers"][0]["this"] is True
    saved = signed_in.put("/api/servers/test/memory", json={"memory_mb": 2048}).json()
    assert saved["ok"] is True
    assert saved["limit_mb"] == 2048


def test_the_version_answer_says_where_the_eula_is(signed_in):
    body = signed_in.get("/api/servers/test/version").json()
    assert body["eula_url"] == "https://aka.ms/MinecraftEULA"
    assert body["minecraft_version"] is None  # not seen in the console yet: Unknown
    assert body["capabilities"]["name"]


def test_crossplay_and_duplicate_answers_are_typed(signed_in):
    cross = signed_in.get("/api/servers/test/crossplay").json()
    assert cross["available"] is True  # the fake server is Fabric
    assert cross["enabled"] is False
    options = signed_in.get("/api/servers/test/duplicate").json()
    assert options["name"].endswith("copy")
    assert options["directory"]


def test_the_only_server_cant_be_removed(signed_in):
    response = signed_in.delete("/api/servers/test")
    assert response.status_code == 400
    assert "only server" in response.json()["detail"]


def test_remove_server_wording_never_says_dashboard():
    strings = json.loads((ROOT / "mobile" / "shared" / "strings.json").read_text(encoding="utf-8"))
    remove = {key: words for key, words in strings.items() if key.startswith("serverset.remove")}
    assert remove
    assert not [
        key for key, words in remove.items() if any("dashboard" in w.lower() for w in words)
    ]


def test_raw_game_settings_are_checked_and_never_half_saved(signed_in):
    before = signed_in.get("/api/servers/test/game-settings").json()["text"]
    refused = signed_in.put(
        "/api/servers/test/game-settings/raw", json={"text": "motd=Hi\nmax-players=lots\n"}
    )
    assert refused.status_code == 400
    assert "max-players" in refused.text
    assert signed_in.get("/api/servers/test/game-settings").json()["text"] == before
    saved = signed_in.put(
        "/api/servers/test/game-settings/raw", json={"text": before + "motd=Hi\n"}
    ).json()
    assert saved["ok"] is True
    assert "motd" in saved["keys"]


def test_java_options_save_through_server_settings(signed_in):
    saved = signed_in.put(
        "/api/servers/test/settings",
        json={"updates": {"server.jvm_args": ["-Xmx2G", "-XX:+UseG1GC"]}},
    ).json()
    assert saved["rejected"] == {}
    assert signed_in.get("/api/servers/test/memory").json()["jvm_args"] == [
        "-Xmx2G",
        "-XX:+UseG1GC",
    ]


def test_the_folder_picker_lists_drives_then_folders_and_refuses_with_a_reason(signed_in, tmp_path):
    top = signed_in.get("/api/folders").json()
    assert top["path"] is None
    assert top["drives"]
    picked = tmp_path / "picked"
    (picked / "world").mkdir(parents=True)
    (picked / "world" / "level.dat").write_bytes(b"")
    inside = signed_in.get("/api/folders", params={"path": str(picked)}).json()
    assert inside["folders"] == [{"name": "world", "path": str(picked / "world"), "world": True}]
    assert inside["parent"] == str(tmp_path)
    refused = signed_in.get("/api/folders", params={"path": "not/whole"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Choose the whole path to a folder."


def test_new_server_options_and_creating_one_are_typed(signed_in, tmp_path, monkeypatch):
    import httpx

    from agent import downloads
    from agent.servertypes import create as create_module

    from .test_server_types import MC, fake_sources

    monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(fake_sources()))
    monkeypatch.setattr(create_module, "java_problem", lambda *args, **kwargs: None)
    options = signed_in.get("/api/new-server/options").json()
    assert options["types"] and options["palette"]
    assert options["bedrock"]["privacy_url"]
    refused = signed_in.post(
        "/api/new-server",
        json={
            "name": "Fresh",
            "directory": str(tmp_path / "fresh"),
            "type": "vanilla",
            "minecraft_version": MC,
        },
    )
    assert refused.status_code == 400
    assert "EULA" in refused.json()["detail"]
    made = signed_in.post(
        "/api/new-server",
        json={
            "name": "Fresh",
            "directory": str(tmp_path / "fresh"),
            "type": "vanilla",
            "minecraft_version": MC,
            "eula_accepted": True,
        },
    ).json()
    assert made["server"]["id"] == made["server_id"]
    assert made["job_id"]


def test_adding_a_server_already_on_the_pc_says_the_agents_warnings(signed_in, tmp_path):
    folder = tmp_path / "skyblock"
    folder.mkdir()
    (folder / "server.jar").write_bytes(b"jar")
    added = signed_in.post(
        "/api/servers", json={"name": "Skyblock", "directory": str(folder), "type": "vanilla"}
    ).json()
    assert added["ok"] is True
    assert added["server"]["name"] == "Skyblock"
    assert isinstance(added["warnings"], list) and added["warnings"]
