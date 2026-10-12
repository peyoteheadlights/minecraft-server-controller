"""Moderators' permissions per server: the owner ticks what each moderator
may do on each server, and the agent checks it on that server for every
route and the live connection."""

import pytest

from agent.api.routes import api_routes
from agent.database.db import Database
from agent.security import permissions as P

from .test_helpers import HELPER_PASSWORD, add_helper, declared, fill, sign_in


@pytest.fixture
def owner(multi_client):
    headers = dict(multi_client.headers)
    multi_client.headers.pop("Authorization")
    return headers


def give(client, owner, grants=None, **extra):
    body = {**extra}
    if grants is not None:
        body["grants"] = {sid: sorted(perms) for sid, perms in grants.items()}
    response = client.put("/api/accounts/sam", json=body, headers=owner)
    assert response.status_code == 200, response.text


def me(client, headers):
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_levels_grow_from_start_and_stop_to_run_it():
    assert P.START_AND_STOP < P.LOOK_AFTER_IT < P.RUN_IT
    assert P.level_of(P.LOOK_AFTER_IT) == "look_after_it"
    assert P.level_of(P.RUN_IT | {P.CONSOLE_SEND, P.CONSOLE_READ}) == "custom"
    assert P.level_of(()) == "none"
    for technical in P.TECHNICAL:
        assert technical not in P.RUN_IT


def test_a_ticked_set_brings_what_it_needs():
    assert P.grant({P.PLAYERS_OP}) == {P.SERVER_VIEW, P.PLAYERS_OP, P.PLAYERS_MANAGE}
    assert P.grant({P.CONSOLE_SEND}) == {P.SERVER_VIEW, P.CONSOLE_SEND, P.CONSOLE_READ}
    assert P.grant(()) == frozenset()
    with pytest.raises(ValueError):
        P.grant({P.USERS_MANAGE})


def test_the_switches_cover_every_server_permission():
    switches = {p for _group, perms in P.GROUPS for p in perms}
    assert switches | {P.SERVER_VIEW} == P.SERVER_PERMISSIONS
    assert not P.SERVER_PERMISSIONS & {
        P.USERS_MANAGE,
        P.SERVERS_MANAGE,
        P.FILES_BROWSE,
        P.DATA_EXPORT,
        P.HELP_BUNDLE,
        P.APP_UPDATE,
        P.PC_SETTINGS,
        P.SECURITY_MANAGE,
    }


def test_different_permissions_on_two_servers(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.START_AND_STOP, "creative": P.RUN_IT})
    c = multi_client
    assert c.get("/api/servers/survival/status", headers=sam).status_code == 200
    assert c.get("/api/servers/survival/logs", headers=sam).status_code == 403
    assert c.get("/api/servers/creative/logs", headers=sam).status_code == 200
    assert c.put("/api/servers/survival/game-settings", json={}, headers=sam).status_code == 403
    assert c.post("/api/servers/survival/backups", json={}, headers=sam).status_code == 403
    assert c.post("/api/servers/creative/backups", json={}, headers=sam).status_code != 403


def test_every_route_checks_on_its_own_server(multi_client, owner):
    """Everything on creative, only start and stop on survival: every
    survival route needing more is refused."""
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.START_AND_STOP, "creative": P.SERVER_PERMISSIONS})
    checked, wrong = 0, []
    for path, route, scope in api_routes():
        permission = declared(route)
        if scope == "global" or permission is None:
            continue
        if permission in P.START_AND_STOP | P.MODERATOR_ACCOUNT:
            continue
        for method in route.methods - {"HEAD"}:
            url = fill(path)  # survival, and the aliases act on survival too
            response = multi_client.request(method, url, json={}, headers=sam)
            checked += 1
            if response.status_code != 403:
                wrong.append(f"{method} {url}: {response.status_code}")
    assert checked > 60
    assert not wrong, wrong


def test_nothing_ticked_hides_the_server(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": set()})
    listed = multi_client.get("/api/servers", headers=sam).json()
    ids = [s["id"] for s in (listed["servers"] if isinstance(listed, dict) else listed)]
    assert "survival" not in ids and "creative" in ids
    assert multi_client.get("/api/servers/survival/status", headers=sam).status_code == 403
    assert "survival" not in me(multi_client, sam)["server_permissions"]


def test_an_all_servers_moderator_gets_new_servers(multi_client, owner):
    add_helper(multi_client, owner)
    give(multi_client, owner, new_server=sorted(P.START_AND_STOP), all_servers=True)
    core = multi_client.app.state.core
    access = core.auth.account("sam")["access"]
    assert access.on("a-server-added-later") == P.START_AND_STOP
    listed = multi_client.get("/api/accounts", headers=owner).json()["helpers"][0]
    assert listed["new_server"]["level"] == "start_and_stop"


def test_a_moderator_limited_to_named_servers_gets_no_new_ones(multi_client, owner):
    add_helper(multi_client, owner, servers=["creative"])
    core = multi_client.app.state.core
    assert core.auth.account("sam")["access"].on("a-server-added-later") == frozenset()


def test_the_sign_in_answer_has_each_servers_permissions(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.START_AND_STOP, "creative": P.RUN_IT})
    answer = me(multi_client, sam)
    assert answer["server_permissions"]["survival"] == sorted(P.START_AND_STOP)
    assert answer["server_permissions"]["creative"] == sorted(P.RUN_IT)
    assert P.ACCOUNT in answer["account_permissions"]
    # Apps released before part 6 read one flat list and the old name.
    assert set(answer["permissions"]) >= P.RUN_IT
    assert "settings.edit" in answer["permissions"]
    owner_answer = me(multi_client, owner)
    assert "settings.edit" in owner_answer["permissions"]
    assert owner_answer["server_permissions"]["survival"] == sorted(P.SERVER_PERMISSIONS)


def test_a_change_applies_without_signing_out(multi_client, owner):
    sam = add_helper(multi_client, owner)
    assert multi_client.get("/api/servers/survival/logs", headers=sam).status_code == 200
    give(multi_client, owner, {"survival": P.START_AND_STOP})
    assert multi_client.get("/api/servers/survival/logs", headers=sam).status_code == 403
    assert multi_client.get("/api/servers/survival/status", headers=sam).status_code == 200


def test_save_for_several_servers_at_once(multi_client, owner):
    add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.RUN_IT, "creative": P.RUN_IT})
    listed = multi_client.get("/api/accounts", headers=owner).json()
    levels = {a["id"]: a["level"] for a in listed["helpers"][0]["access"]}
    assert levels["survival"] == levels["creative"] == "run_it"
    assert listed["permissions"]["default_level"] == "look_after_it"


def test_the_owner_cant_give_an_owner_only_permission(multi_client, owner):
    add_helper(multi_client, owner)
    response = multi_client.put(
        "/api/accounts/sam", json={"grants": {"survival": ["users.manage"]}}, headers=owner
    )
    assert response.status_code == 400
    response = multi_client.put(
        "/api/accounts/sam", json={"grants": {"nowhere": ["server.view"]}}, headers=owner
    )
    assert response.status_code == 400


def test_game_server_and_pc_settings_are_separate(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.LOOK_AFTER_IT | {P.SETTINGS_GAME}})
    c = multi_client
    assert c.put("/api/servers/survival/game-settings", json={}, headers=sam).status_code != 403
    assert c.put("/api/servers/survival/memory", json={}, headers=sam).status_code == 403
    assert c.put("/api/settings", json={"values": {}}, headers=sam).status_code == 403
    give(multi_client, owner, {"survival": P.LOOK_AFTER_IT | {P.SETTINGS_SERVER}})
    assert c.put("/api/servers/survival/memory", json={}, headers=sam).status_code != 403
    assert c.put("/api/servers/survival/game-settings", json={}, headers=sam).status_code == 403


def test_owner_only_routes_refuse_every_moderator(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.SERVER_PERMISSIONS, "creative": P.SERVER_PERMISSIONS})
    wrong = []
    for path, route, _scope in api_routes():
        permission = declared(route)
        if permission is None or permission in P.SERVER_PERMISSIONS | P.MODERATOR_ACCOUNT:
            continue
        for method in route.methods - {"HEAD"}:
            response = multi_client.request(method, fill(path), json={}, headers=sam)
            if response.status_code != 403:
                wrong.append(f"{method} {path}: {response.status_code}")
    assert not wrong, wrong


def test_old_helpers_keep_what_they_had(multi, tmp_path):
    """A helper saved before per-server permissions reads as "Look after
    it" on the same servers."""
    db = Database(multi.database_path)
    db.execute(
        "INSERT INTO accounts (username, password_hash, role, servers, created_at) "
        "VALUES ('old', 'x', 'helper', '[\"creative\"]', 0)"
    )
    db.execute(
        "INSERT INTO accounts (username, password_hash, role, servers, created_at) "
        "VALUES ('everywhere', 'x', 'helper', NULL, 0)"
    )
    from agent.security.auth import AuthManager

    auth = AuthManager.__new__(AuthManager)
    auth.db = db
    limited = auth.account("old")["access"]
    assert limited.on("creative") == P.LOOK_AFTER_IT
    assert limited.on("survival") == frozenset()
    everywhere = auth.account("everywhere")["access"]
    assert everywhere.on("survival") == everywhere.on("anything-new") == P.LOOK_AFTER_IT
    db.close()


def test_the_live_connection_leaves_out_the_console_without_reading_it(multi_client, owner):
    sam = add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.START_AND_STOP, "creative": set()})
    token = sam["Authorization"].split()[1]
    with multi_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token, "server_id": "survival"})
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["console"] == []
        ws.send_json({"type": "tail", "server_id": "survival"})
        while True:
            answer = ws.receive_json()
            if answer["type"] in ("denied", "console_tail"):
                break
        assert answer["type"] == "denied"


def test_alerts_follow_what_a_moderator_can_see_now(multi_client, owner):
    sam = add_helper(multi_client, owner)
    core = multi_client.app.state.core
    core.db.insert(
        "app_alerts",
        {
            "server_id": "survival",
            "ts": 1.0,
            "event": "crash",
            "title": "x",
            "body": "x",
            "page": "overview",
            "url": "/",
        },
    )

    def survival_alerts():
        response = multi_client.get("/api/alerts?after=0", headers=sam)
        assert response.status_code == 200, response.text
        return [a for a in response.json()["alerts"] if a.get("server_id") == "survival"]

    assert survival_alerts()
    assert core.auth.may_see_alert("sam", "survival")
    give(multi_client, owner, {"survival": set()})
    assert not survival_alerts()
    assert not core.auth.may_see_alert("sam", "survival")
    give(multi_client, owner, {"survival": P.START_AND_STOP})
    assert survival_alerts()


def test_a_moderator_signs_in_after_their_permissions_change(multi_client, owner):
    add_helper(multi_client, owner)
    give(multi_client, owner, {"survival": P.RUN_IT})
    assert sign_in(multi_client, "sam", HELPER_PASSWORD)


def test_no_screen_says_helper_any_more():
    """Screens say "moderator"; code, database and API names keep "helper"
    until Phase 12."""
    import json
    import re
    from pathlib import Path

    from agent.notifications.dispatcher import EVENT_MAP

    root = Path(__file__).resolve().parents[1]
    word = re.compile(r"\bhelpers?\b", re.IGNORECASE)
    said = []
    table = (root / "agent/web/js/strings.js").read_text(encoding="utf-8")
    for line in table.splitlines():
        match = re.match(r'^\s*"[^"]+":\s*(\[.*)$', line)
        if match and word.search(match.group(1)):
            said.append(line.strip())
    for key, pair in json.loads((root / "mobile/shared/strings.json").read_text("utf-8")).items():
        if word.search(json.dumps(pair)):
            said.append(key)
    said += [entry[3] for entry in EVENT_MAP.values() if word.search(entry[3])]
    assert not said, said
