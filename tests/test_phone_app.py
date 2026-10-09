"""Phase 9: what the agent does for the phone app (mobile/). The app's own
screens and pairing are tested in mobile/shell/test; these cover the agent
side: the alert list the app reads, who sees which alert, and that signing
out on the PC locks the app out."""

import asyncio
import logging
from pathlib import Path

import pytest

from agent.events import Event
from agent.notifications import dispatcher

from .test_helpers import add_helper

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def owner(multi_client):
    return dict(multi_client.headers)


def alerts_on(client, on=True):
    core = client.app.state.core
    response = client.put("/api/settings", json={"updates": {"notifications.push_enabled": on}})
    assert response.status_code == 200, response.text
    assert core.config.notifications.push_enabled is on
    return core


def send(core, event):
    async def go():
        await core.notifier.deliver(event)

    asyncio.run(go())


def crash(server_id="survival"):
    return Event(type="server_crashed", level="error", message="It crashed", server_id=server_id)


def test_an_alert_is_kept_for_the_app_when_phone_alerts_are_on(multi_client):
    core = alerts_on(multi_client)
    start = multi_client.get("/api/alerts").json()
    assert start["alerts"] == [] and start["enabled"] is True
    send(core, crash())
    result = multi_client.get("/api/alerts", params={"after": start["latest"]}).json()
    [alert] = result["alerts"]
    assert alert["title"].endswith("Survival crashed")
    assert alert["server_id"] == "survival"
    # Tapping it opens that server's crash page, as Web Push alerts do.
    assert alert["url"] == "/#survival/crashes"
    assert result["latest"] == alert["id"]
    # Asked again from there, nothing repeats.
    again = multi_client.get("/api/alerts", params={"after": result["latest"]}).json()
    assert again["alerts"] == []


def test_nothing_is_kept_while_phone_alerts_are_off(multi_client):
    core = alerts_on(multi_client, False)
    send(core, crash())
    assert core.db.query("SELECT * FROM app_alerts") == []
    assert multi_client.get("/api/alerts").json()["enabled"] is False


def test_a_new_phone_doesnt_replay_old_alerts(multi_client):
    core = alerts_on(multi_client)
    send(core, crash())
    first = multi_client.get("/api/alerts").json()
    assert first["alerts"] == [] and first["latest"] > 0


def test_a_helper_sees_only_their_servers_alerts(multi_client, owner):
    core = alerts_on(multi_client)
    helper = add_helper(multi_client, owner, servers=["creative"])
    send(core, crash("survival"))
    send(core, crash("creative"))
    send(core, Event(type="auth_failure", level="warn", message="Wrong password"))
    multi_client.headers.pop("Authorization")
    seen = multi_client.get("/api/alerts", params={"after": 0}, headers=helper).json()
    assert [a["server_id"] for a in seen["alerts"]] == ["creative"]
    everything = multi_client.get("/api/alerts", params={"after": 0}, headers=owner).json()
    # (adding the helper sent its own alert about the PC first)
    shown = [(a["event"], a["server_id"]) for a in everything["alerts"]]
    assert shown[-3:] == [
        ("server_crashed", "survival"),
        ("server_crashed", "creative"),
        ("auth_failure", None),
    ]


def test_only_the_newest_alerts_are_kept(multi_client, monkeypatch):
    core = alerts_on(multi_client)
    monkeypatch.setattr(dispatcher, "APP_ALERTS_KEPT", 3)
    for _ in range(6):
        send(core, Event(type="backup_completed", level="success", server_id="survival"))
    assert [r["id"] for r in core.db.query("SELECT id FROM app_alerts")] == [4, 5, 6]


def test_a_long_list_comes_in_pages(multi_client):
    core = alerts_on(multi_client)
    for _ in range(5):
        send(core, Event(type="backup_completed", level="success", server_id="survival"))
    page = multi_client.get("/api/alerts", params={"after": 0, "limit": 2}).json()
    assert len(page["alerts"]) == 2
    rest = multi_client.get("/api/alerts", params={"after": page["latest"], "limit": 50}).json()
    assert len(rest["alerts"]) == 3


def test_the_test_alert_reaches_the_app(multi_client):
    core = alerts_on(multi_client)
    result = multi_client.post("/api/push/test").json()
    assert result["for_app"] is True
    [row] = core.db.query("SELECT title FROM app_alerts")
    assert row["title"] == dispatcher.PUSH_TEST_TITLE


def test_signing_the_phone_out_on_the_pc_locks_the_app(multi_client, owner):
    phone = multi_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct horse battery", "device": "Android app"},
    ).json()
    headers = {"Authorization": f"Bearer {phone['token']}"}
    assert multi_client.get("/api/servers", headers=headers).status_code == 200
    sessions = multi_client.get("/api/sessions", headers=owner).json()["sessions"]
    [entry] = [s for s in sessions if s["label"] == "Android app"]
    assert multi_client.delete(f"/api/sessions/{entry['id']}", headers=owner).status_code == 200
    # What the app and its widget ask for next is refused: the app then
    # forgets the token (mobile/shell/test covers that side).
    for path in ("/api/servers", "/api/alerts", "/api/auth/me"):
        assert multi_client.get(path, headers=headers).status_code == 401


def test_the_app_shows_unknown_players_until_measured(multi_client):
    """The widget shows what /api/servers says: a player count is either
    measured or null (Unknown), never a guess."""
    rows = multi_client.get("/api/servers").json()["servers"]
    assert rows
    for row in rows:
        if row["state"] == "UNKNOWN":
            assert row["players_online"] is None
        if row["players_online"] is not None and row["state"] != "OFFLINE":
            assert row["players_verified"] is True


def test_no_token_reaches_the_log(multi_client, caplog):
    caplog.set_level(logging.DEBUG)
    phone = multi_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct horse battery"}
    ).json()
    multi_client.get("/api/alerts", headers={"Authorization": f"Bearer {phone['token']}"})
    assert phone["token"] not in caplog.text
    assert "correct horse battery" not in caplog.text


def test_every_route_the_app_uses_exists_and_is_typed():
    """The agent stays backward-compatible with the app: every route listed
    in mobile/api-routes.txt must keep existing with a typed answer."""
    from .test_api_contract import routes

    current = routes()
    listed = (ROOT / "mobile" / "api-routes.txt").read_text(encoding="utf-8").splitlines()
    used = [line.strip() for line in listed if line.strip() and not line.startswith("#")]
    assert "GET /api/alerts" in used
    for name in used:
        assert name in current, f"the phone app uses {name}, which is gone"
        assert current[name].response_model is not None, name
