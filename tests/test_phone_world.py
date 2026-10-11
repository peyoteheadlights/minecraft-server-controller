"""The routes the phone apps' Backups, Restore world, Schedules and
Performance screens call, answered in the shapes their typed models
promise (agent/api/responses.py, mobile/api-routes.txt)."""

from __future__ import annotations

from .test_api import auth, token_for


def test_the_backup_list_says_what_is_kept_and_where_each_copy_is(client):
    headers = auth(token_for(client))
    made = client.post("/api/backups", json={}, headers=headers).json()
    assert made["ok"] is True and made["name"]

    listed = client.get("/api/backups", headers=headers).json()
    backup = next(b for b in listed["backups"] if b["id"] == made["id"])
    assert backup["exists"] is True
    assert backup["status"] == "ok"
    assert backup["copy"]["state"] == "none"
    assert set(listed["retention"]) >= {"daily", "weekly", "monthly"}

    check = client.get(f"/api/backups/{made['id']}/verify", headers=headers).json()
    assert check["ok"] is True and check["entries"] > 0

    gone = client.delete(f"/api/backups/{made['id']}", headers=headers).json()
    assert gone == {"ok": True, "deleted": made["name"]}


def test_a_second_copy_is_made_and_turned_off_again(client, tmp_path):
    headers = auth(token_for(client))
    assert client.get("/api/backups/offsite", headers=headers).json()["directory"] == ""
    folder = tmp_path / "usb"
    folder.mkdir()
    saved = client.put("/api/backups/offsite", json={"directory": str(folder)}, headers=headers)
    assert saved.status_code == 200, saved.text
    status = client.get("/api/backups/offsite", headers=headers).json()
    assert status["directory"] and status["unavailable"] is None

    made = client.post("/api/backups", json={}, headers=headers).json()
    again = client.post(f"/api/backups/{made['id']}/copy", headers=headers).json()
    assert again["ok"] is True and again["copy"]["state"] == "ok"

    off = client.put("/api/backups/offsite", json={"directory": ""}, headers=headers).json()
    assert off == {"ok": True, "directory": ""}


def test_a_schedule_is_added_switched_off_run_and_deleted(client):
    headers = auth(token_for(client))
    listed = client.get("/api/schedules", headers=headers).json()
    assert "backup" in listed["tasks"]
    body = {"name": "Tidy logs", "task": "log_cleanup", "kind": "daily", "expr": "04:00"}
    made = client.post("/api/schedules", json=body, headers=headers).json()["schedule"]
    assert made["enabled"] is True and made["next_run"]

    off = client.put(
        f"/api/schedules/{made['id']}", json={**body, "enabled": False}, headers=headers
    ).json()
    assert off["schedule"]["enabled"] is False

    ran = client.post(f"/api/schedules/{made['id']}/run", headers=headers).json()
    assert ran["ok"] is True and isinstance(ran["result"], str)

    assert client.delete(f"/api/schedules/{made['id']}", headers=headers).json() == {"ok": True}
    left = client.get("/api/schedules", headers=headers).json()["schedules"]
    assert made["id"] not in [s["id"] for s in left]


def test_performance_answers_gaps_as_null_and_storage_only_when_asked(client):
    headers = auth(token_for(client))
    data = client.get("/api/performance?hours=1", headers=headers).json()
    assert set(data["series"]) >= {"points", "hours", "bucket_seconds"}
    assert data["sample_interval"] > 0
    # The server isn't running: its memory isn't measured, so it is null.
    assert data["current"]["proc_ram_mb"] is None
    assert "worlds_gb" in data["storage"]
    quick = client.get("/api/performance?hours=1&storage=false", headers=headers).json()
    assert quick["storage"] is None


def test_the_health_checks_never_count_an_unknown_as_passing(client):
    headers = auth(token_for(client))
    health = client.get("/api/health/server", headers=headers).json()
    assert health["overall"] in ("ALL CHECKS VERIFIED", "PARTIALLY VERIFIED", "ATTENTION NEEDED")
    statuses = {check["status"] for check in health["checks"]}
    assert statuses <= {"ok", "warn", "unknown"}
    if "unknown" in statuses:
        assert health["overall"] != "ALL CHECKS VERIFIED"


def test_the_worlds_and_the_restore_world_points_are_listed(client):
    headers = auth(token_for(client))
    client.post("/api/backups", json={}, headers=headers)
    worlds = client.get("/api/worlds", headers=headers).json()["worlds"]
    assert [w["label"] for w in worlds] == ["Overworld", "Nether", "The End"]
    server = client.get("/api/servers", headers=headers).json()["servers"][0]["id"]
    timeline = client.get(f"/api/servers/{server}/world/timeline", headers=headers).json()
    assert timeline["points"] and timeline["points"][0]["checked"] is True
    assert timeline["can_restore"] is True


def test_a_backup_downloads_with_the_token_in_a_header(client):
    headers = auth(token_for(client))
    made = client.post("/api/backups", json={}, headers=headers).json()
    server = client.get("/api/servers", headers=headers).json()["servers"][0]["id"]
    path = f"/api/servers/{server}/backups/{made['id']}/download"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert made["name"] in response.headers["content-disposition"]
    assert response.content[:2] == b"PK"
