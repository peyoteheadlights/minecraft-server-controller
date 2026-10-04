import pytest

from agent.security.auth import hash_password, verify_password

from .conftest import PASSWORD


def token_for(client) -> str:
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- hashing
def test_password_hashing_round_trips_and_rejects_wrong_input():
    encoded = hash_password("a long enough password", rounds=1000)
    assert verify_password("a long enough password", encoded)
    assert not verify_password("something else", encoded)
    assert "a long enough password" not in encoded


def test_short_passwords_are_refused():
    with pytest.raises(ValueError):
        hash_password("short")


# ---------------------------------------------------------------- auth
def test_health_is_public_but_reveals_nothing_sensitive(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert "directory" not in body


@pytest.mark.parametrize("path", [
    "/api/status", "/api/mods", "/api/backups", "/api/players",
    "/api/settings", "/api/security", "/api/events", "/api/crashes",
])
def test_every_data_route_requires_a_token(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", [
    "/api/server/start", "/api/server/stop", "/api/server/restart",
    "/api/backups", "/api/mods/install", "/api/mods/remove",
])
def test_every_action_route_requires_a_token(client, path):
    assert client.post(path, json={}).status_code == 401


def test_a_bad_token_is_refused(client):
    assert client.get("/api/status", headers=auth("not-a-real-token")).status_code == 401


def test_login_then_use_then_logout(client):
    token = token_for(client)
    assert client.get("/api/status", headers=auth(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/status", headers=auth(token)).status_code == 401


def test_wrong_password_is_refused_and_recorded(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert "not correct" in response.json()["detail"]


def test_repeated_failures_lock_the_account_out(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_token_rotation_invalidates_the_old_token(client):
    token = token_for(client)
    new_token = client.post("/api/auth/rotate", headers=auth(token)).json()["token"]
    assert new_token != token
    assert client.get("/api/status", headers=auth(new_token)).status_code == 200
    assert client.get("/api/status", headers=auth(token)).status_code == 401


def test_revoking_sessions_signs_everyone_out(client):
    first, second = token_for(client), token_for(client)
    assert client.post("/api/security/revoke-sessions", headers=auth(first)).status_code == 200
    assert client.get("/api/status", headers=auth(second)).status_code == 401


def test_api_token_from_the_environment_works(client, monkeypatch):
    monkeypatch.setenv("MCSC_API_TOKEN", "a-long-script-token-value")
    assert client.get("/api/status", headers=auth("a-long-script-token-value")).status_code == 200
    assert client.get("/api/status", headers=auth("a-long-script-token-valuX")).status_code == 401


# ---------------------------------------------------------------- behaviour
def test_dangerous_commands_need_confirmation_through_the_api(client):
    token = token_for(client)
    response = client.post("/api/server/command", json={"command": "stop"}, headers=auth(token))
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"]


def test_commands_are_refused_when_the_server_is_offline(client):
    token = token_for(client)
    response = client.post("/api/server/command", json={"command": "say hi"}, headers=auth(token))
    assert response.status_code == 409


def test_shell_injection_through_the_command_api_is_refused(client):
    token = token_for(client)
    for payload in ["say hi; shutdown /s", "say hi\nstop", "say `calc`"]:
        response = client.post("/api/server/command",
                               json={"command": payload, "confirm": True}, headers=auth(token))
        assert response.status_code == 400


def test_settings_updates_are_limited_to_an_allow_list(client):
    token = token_for(client)
    response = client.put("/api/settings", headers=auth(token), json={"updates": {
        "thresholds.cpu_percent": 75,
        "server.directory": "C:\\somewhere\\else",
        "server.raw_command": ["cmd.exe", "/c", "calc"],
    }})
    body = response.json()
    assert body["applied"] == {"thresholds.cpu_percent": 75}
    assert "server.directory" in body["rejected"]
    assert "server.raw_command" in body["rejected"]


def test_restore_returns_a_confirmation_payload_before_acting(client, config):
    token = token_for(client)
    created = client.post("/api/backups", json={}, headers=auth(token)).json()
    response = client.post(f"/api/backups/{created['id']}/restore",
                           json={"confirm": False}, headers=auth(token))
    body = response.json()
    assert body["confirmation_required"] is True
    assert any("safety backup" in step.lower() for step in body["will_happen"])


def test_mod_upload_rejects_an_executable(client):
    token = token_for(client)
    response = client.post("/api/mods/upload", headers=auth(token),
                           files={"file": ("payload.exe", b"MZ", "application/octet-stream")})
    assert response.status_code == 400


def test_security_headers_are_present(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


# ---------------------------------------------------------------- websocket
def test_websocket_requires_authentication_first(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "tail", "lines": 10})
        message = ws.receive_json()
        assert message["type"] == "error"


def test_websocket_rejects_a_bad_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "nope"})
        assert ws.receive_json()["type"] == "error"


def test_websocket_streams_after_authentication(client):
    token = token_for(client)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert "status" in ready
        ws.send_json({"type": "tail", "lines": 5})
        assert ws.receive_json()["type"] == "console_tail"
