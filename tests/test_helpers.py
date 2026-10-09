"""Helper accounts: what a helper may and may not do, enforced on the agent
for every route and the live connection, plus the owner-only password reset."""

import re

import pytest

from agent.api.routes import api_routes
from agent.security import permissions

from .conftest import PASSWORD

HELPER_PASSWORD = "helper password 123"


def sign_in(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def add_helper(client, owner, username="sam", servers=None):
    body = {"username": username, "password": HELPER_PASSWORD}
    if servers is not None:
        body["servers"] = servers
    response = client.post("/api/accounts", json=body, headers=owner)
    assert response.status_code == 200, response.text
    return sign_in(client, username, HELPER_PASSWORD)


@pytest.fixture
def owner(multi_client):
    return dict(multi_client.headers)


def fill(path: str) -> str:
    def value(match):
        name = match.group(1)
        if name == "server_id":
            return "survival"
        if name.endswith("_id") or name in ("index",):
            return "1"
        return "x"

    return re.sub(r"\{([a-z_]+)(?::[a-z]+)?\}", value, path)


def declared(route) -> str | None:
    for dep in route.dependant.dependencies:
        if hasattr(dep.call, "permission"):
            return dep.call.permission
    return None


def test_the_helper_role_is_what_the_prompt_says():
    helper = permissions.HELPER_PERMISSIONS
    for allowed in (
        permissions.SERVER_CONTROL,
        permissions.PLAYERS_MANAGE,
        permissions.CHAT_SEND,
        permissions.SERVER_VIEW,
    ):
        assert allowed in helper
    for forbidden in (
        permissions.SETTINGS_EDIT,
        permissions.BACKUPS_DELETE,
        permissions.MODS_MANAGE,
        permissions.USERS_MANAGE,
        permissions.SERVERS_MANAGE,
        permissions.CONSOLE_SEND,
        permissions.SECURITY_VIEW,
    ):
        assert forbidden not in helper


def test_every_route_a_helper_may_not_use_returns_403(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    checked, wrong = 0, []
    for path, route, _scope in api_routes():
        permission = declared(route)
        if permission is None or permission in permissions.HELPER_PERMISSIONS:
            continue
        for method in route.methods:
            if method == "HEAD":
                continue
            response = multi_client.request(method, fill(path), json={}, headers=helper)
            checked += 1
            if response.status_code != 403:
                wrong.append(f"{method} {path}: {response.status_code}")
    assert checked > 60
    assert not wrong, wrong


def test_a_helper_can_do_the_everyday_things(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    assert multi_client.get("/api/servers/survival/status", headers=helper).status_code == 200
    assert multi_client.get("/api/auth/me", headers=helper).json()["role"] == "helper"
    assert multi_client.get("/api/servers/survival/backups", headers=helper).status_code == 200
    me = multi_client.get("/api/auth/me", headers=helper).json()
    assert "users.manage" not in me["permissions"]


def test_a_helper_limited_to_one_server_cant_reach_the_other(multi_client, owner):
    helper = add_helper(multi_client, owner, servers=["creative"])
    multi_client.headers.pop("Authorization")
    assert multi_client.get("/api/servers/creative/status", headers=helper).status_code == 200
    assert multi_client.get("/api/servers/survival/status", headers=helper).status_code == 403
    # the unprefixed routes act on the first server, survival
    assert multi_client.get("/api/status", headers=helper).status_code == 403
    listed = multi_client.get("/api/servers", headers=helper).json()
    ids = [s["id"] for s in (listed["servers"] if isinstance(listed, dict) else listed)]
    assert ids == ["creative"]


def test_the_live_connection_only_carries_the_helpers_servers(multi_client, owner):
    helper = add_helper(multi_client, owner, servers=["creative"])
    token = helper["Authorization"].split()[1]
    with multi_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token, "server_id": "survival"})
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert [s["id"] for s in ready["servers"]] == ["creative"]
        assert ready["server_id"] == "creative"  # asking for survival gives creative


def test_helper_passwords_are_hashed_like_the_owners(multi_client, owner):
    add_helper(multi_client, owner)
    core = multi_client.app.state.core
    row = core.db.query_one("SELECT password_hash FROM accounts WHERE username = 'sam'")
    assert row["password_hash"].startswith("pbkdf2_sha256$")
    assert HELPER_PASSWORD not in row["password_hash"]
    listed = multi_client.get("/api/accounts", headers=owner).json()
    assert "password_hash" not in str(listed)


def test_the_audit_log_says_who_did_what(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    multi_client.post("/api/servers/survival/backups", json={}, headers=helper)
    multi_client.put("/api/settings", json={"values": {}}, headers=helper)  # refused
    core = multi_client.app.state.core
    rows = core.db.query("SELECT user, action, result FROM audit_log WHERE user = 'sam'")
    results = {r["result"] for r in rows}
    assert rows, "a helper's actions are logged under their name"
    assert "denied" in results


def test_lockout_is_per_account(multi_client, owner):
    add_helper(multi_client, owner)
    for _ in range(12):
        multi_client.post("/api/auth/login", json={"username": "sam", "password": "wrong guess!!"})
    response = multi_client.post(
        "/api/auth/login", json={"username": "sam", "password": HELPER_PASSWORD}
    )
    assert response.status_code in (401, 429)


def test_removing_a_helper_signs_them_out(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    assert multi_client.delete("/api/accounts/sam", headers=owner).status_code == 200
    assert multi_client.get("/api/auth/me", headers=helper).status_code == 401


def test_a_helper_changes_their_own_password(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    response = multi_client.post(
        "/api/account/password",
        json={"current": HELPER_PASSWORD, "new": "a brand new one 456"},
        headers=helper,
    )
    assert response.status_code == 200, response.text
    sign_in(multi_client, "sam", "a brand new one 456")


def test_the_owner_password_cant_be_changed_over_the_network(multi_client, owner):
    response = multi_client.post(
        "/api/account/password", json={"current": PASSWORD, "new": "another password 1"}
    )
    assert response.status_code == 400
    assert "reset_password" in response.json()["detail"]


def test_password_reset_has_no_route():
    for path, route, _scope in api_routes():
        assert "reset" not in path.lower() or "password" not in path.lower(), path
        assert "reset_password" not in getattr(route.endpoint, "__module__", "")
    import installer.reset_password as tool

    source = open(tool.__file__, encoding="utf-8").read()
    assert "fastapi" not in source and "APIRouter" not in source


def test_password_reset_on_the_pc(multi, tmp_path, monkeypatch):
    from agent.database.db import Database
    from agent.security.auth import verify_password
    from installer import reset_password, setup_tool

    env = tmp_path / ".env"
    env.write_text("MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH=old\n", encoding="utf-8")
    multi.save(tmp_path / "config.yaml")
    db = Database(multi.database_path)
    db.execute(
        "INSERT INTO sessions (token_hash, user, created_at, expires_at, last_used) "
        "VALUES ('abc', 'admin', 0, 9999999999, 0)"
    )
    db.close()
    answers = iter(["short", "x", "new password 789", "new password 789"])
    said = []
    code = reset_password.reset(
        tmp_path / "config.yaml", env, ask=lambda _: next(answers), say=said.append
    )
    assert code == 0
    values = setup_tool.read_env(env)
    assert verify_password("new password 789", values["MCSC_ADMIN_PASSWORD_HASH"])
    assert not any("new password 789" in line for line in said)
    db = Database(multi.database_path)
    assert db.query("SELECT * FROM sessions") == []
    assert db.query_one("SELECT * FROM audit_log WHERE action = 'password_reset'")
