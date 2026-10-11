"""What the phone apps' Setup screens (Phase 9 part 5) need from the agent:
Server settings, version and type changes, the raw editors, new servers,
the PC folder picker and world import."""

from __future__ import annotations

import pytest

from .test_api import auth, token_for


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
    body = signed_in.put("/api/servers/test/settings", json={"updates": {"server.java": "x"}}).json()
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
