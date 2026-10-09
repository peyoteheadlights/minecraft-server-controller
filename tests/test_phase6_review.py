"""Problems the Phase 6 review found, each with the test that would have
caught it: operators and helpers, a helper's servers changing while their
page is open, the memory slider and -Xms, keep awake turned off while a
server runs, two servers with the same folder name moving to a new PC, a
world picked from the server's own folder, the .mcworld download name, and
a password reset that can't write .env."""

import pytest

from agent import memory, transfer
from agent.api import ws

from .conftest import PASSWORD
from .test_helpers import add_helper


@pytest.fixture
def owner(multi_client):
    return dict(multi_client.headers)


def sign_in_owner(client):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"


# ------------------------------------------------------------------ operators
def test_a_helper_cant_make_anyone_an_operator(multi_client, owner):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    for action in ("op", "deop"):
        refused = multi_client.post(
            "/api/servers/survival/players/actions",
            json={"action": action, "name": "Sam"},
            headers=helper,
        )
        assert refused.status_code == 403, refused.text
    me = multi_client.get("/api/auth/me", headers=helper).json()
    assert "players.op" not in me["permissions"]
    assert "players.manage" in me["permissions"]
    # the owner still can (the answer is whatever the stopped server allows,
    # but never a refusal of the permission)
    allowed = multi_client.post(
        "/api/servers/survival/players/actions",
        json={"action": "op", "name": "Sam"},
        headers=owner,
    )
    assert allowed.status_code != 403


# ------------------------------------------------------------------ live connection
def test_the_live_connection_follows_a_change_to_the_helpers_servers(
    multi_client, owner, monkeypatch
):
    monkeypatch.setattr(ws, "HEARTBEAT", 0.2)
    helper = add_helper(multi_client, owner)
    token = helper["Authorization"].split()[1]
    with multi_client.websocket_connect("/ws") as live:
        live.send_json({"type": "auth", "token": token, "server_id": "survival"})
        ready = live.receive_json()
        assert ready["server_id"] == "survival"
        changed = multi_client.put(
            "/api/accounts/sam", json={"servers": ["creative"]}, headers=owner
        )
        assert changed.status_code == 200
        # the next heartbeat reads the account again
        for _ in range(50):
            if live.receive_json()["type"] == "ping":
                break
        live.send_json({"type": "tail", "server_id": "survival"})
        for _ in range(50):
            message = live.receive_json()
            if message["type"] == "console_tail":
                assert message["server_id"] == "creative"
                break
        else:
            raise AssertionError("no console answer came")


# ------------------------------------------------------------------ memory
def test_a_starting_size_above_the_new_limit_is_lowered():
    args = ["-Xms4G", "-Xmx4G", "-XX:+UseG1GC"]
    assert memory.with_limit(args, 2048) == ["-Xms2G", "-Xmx2G", "-XX:+UseG1GC"]
    assert memory.with_limit(["-Xms512M", "-Xmx1G"], 2048) == ["-Xms512M", "-Xmx2G"]
    assert memory.with_limit(["-Xms3000m"], 2560) == ["-Xms2560M", "-Xmx2560M"]


# ------------------------------------------------------------------ keep awake
def test_turning_keep_awake_off_tells_windows_at_once(client, monkeypatch):
    sign_in_owner(client)
    core = client.app.state.core
    calls = []
    monkeypatch.setattr(core.keepawake, "update", lambda: calls.append(1))
    response = client.put("/api/settings", json={"updates": {"power.keep_awake": False}})
    assert response.status_code == 200, response.text
    assert response.json()["applied"] == {"power.keep_awake": False}
    assert calls, "the change reaches Windows now, not at the next start or stop"


# ------------------------------------------------------------------ moving to a new PC
def test_two_servers_with_the_same_folder_name_get_their_own_folders(tmp_path):
    manifest = {
        "servers": [
            {"id": "a", "name": "A", "directory": "C:\\A\\server", "folder_name": "server"},
            {"id": "b", "name": "B", "directory": "D:\\B\\server", "folder_name": "Server"},
        ]
    }
    places = transfer.plan_import(manifest, tmp_path)
    assert [p["to"] for p in places] == [str(tmp_path / "server"), str(tmp_path / "Server (2)")]


# ------------------------------------------------------------------ world import
def test_a_world_inside_the_servers_own_folder_is_refused(client):
    sign_in_owner(client)
    server_dir = client.app.state.core.default.config.server_dir
    own = server_dir / "world"
    assert (own / "level.dat").is_file()
    picked = client.post("/api/servers/test/world/import/folder", json={"path": str(own)})
    assert picked.status_code == 200, picked.text
    refused = client.post(
        "/api/servers/test/world/import",
        json={"token": picked.json()["token"], "confirm": True},
    )
    assert refused.status_code == 400
    assert "own folder" in refused.json()["detail"]
    assert (own / "level.dat").is_file(), "the world was left where it was"
    assert not list(server_dir.glob("*.replaced-*"))


def test_a_bedrock_download_keeps_its_mcworld_name(client):
    sign_in_owner(client)
    packed = client.post("/api/servers/test/world/download")
    assert packed.status_code == 200, packed.text
    got = client.get(
        f"/api/servers/test/world/download/{packed.json()['token']}",
        params={"filename": "My World.mcworld"},
    )
    assert got.status_code == 200
    disposition = got.headers["content-disposition"]
    assert disposition.endswith("My%20World.mcworld"), disposition


# ------------------------------------------------------------------ password reset
def test_a_reset_that_cant_write_env_says_so_plainly(multi, tmp_path, monkeypatch):
    from installer import reset_password

    env = tmp_path / ".env"
    env.write_text("MCSC_ADMIN_USERNAME=admin\nMCSC_ADMIN_PASSWORD_HASH=old\n", encoding="utf-8")
    multi.save(tmp_path / "config.yaml")

    def refuse(*_args):
        raise PermissionError(13, "Access is denied", str(env))

    monkeypatch.setattr(reset_password, "write_env_value", refuse)
    answers = iter(["new password 789", "new password 789"])
    said: list[str] = []
    code = reset_password.reset(
        tmp_path / "config.yaml", env, ask=lambda _: next(answers), say=said.append
    )
    assert code == 1
    assert any("administrator" in line for line in said)
    assert "MCSC_ADMIN_PASSWORD_HASH=old" in env.read_text(encoding="utf-8")
