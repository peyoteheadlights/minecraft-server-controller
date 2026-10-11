"""The routes the phone apps' Mods / Plugins / Packs and Game settings
screens call (Phase 9 part 4): Update all, and every other route those
screens use answering in the shape its typed model promises
(agent/api/responses.py, mobile/api-routes.txt).

Modrinth is the fake from test_dependency_resolution, whose downloads are
real jar files, so updates run end to end through the real ModManager."""

from __future__ import annotations

import time

import pytest

from agent.mods.modrinth import ModrinthError

from .test_api import auth, token_for
from .test_dependency_resolution import FakeModrinth
from .test_helpers import add_helper
from .test_mods import make_jar

PROJECTS = {
    "alpha": {"project_id": "ALPHA001", "title": "Alpha", "versions": [("2.0", [])]},
    "beta": {"project_id": "BETA0001", "title": "Beta", "versions": [("2.0", [])]},
    "gamma": {"project_id": "GAMMA001", "title": "Gamma", "versions": [("1.0", [])]},
}


class BrokenModrinth(FakeModrinth):
    """Downloads of the projects in ``broken`` fail, as a dropped
    connection to Modrinth would."""

    def __init__(self, projects, broken):
        super().__init__(projects)
        self.broken = set(broken)

    async def download(self, version):
        if self.by_id[version["project_id"]] in self.broken:
            raise ModrinthError("Modrinth stopped answering.")
        return await super().download(version)


@pytest.fixture
def mods_dir(config):
    folder = config.mods_dir
    make_jar(folder / "alpha.jar", "alpha", version="1.0", name="Alpha")
    make_jar(folder / "beta.jar.disabled", "beta", version="1.0", name="Beta")
    make_jar(folder / "gamma.jar", "gamma", version="1.0", name="Gamma")
    return folder


def use(client, modrinth):
    core = client.app.state.core
    core.mods.modrinth = modrinth
    return core


def installed(client, headers):
    mods = client.get("/api/mods", headers=headers).json()["mods"]
    return {m["mod_id"]: (m["version"], m["enabled"]) for m in mods}


def safety_backups(client, headers):
    backups = client.get("/api/backups", headers=headers).json()["backups"]
    return [b for b in backups if b["kind"] == "safety"]


# ------------------------------------------------------------ Update all
def test_the_plan_lists_only_mods_with_a_newer_version_and_marks_turned_off_ones(client, mods_dir):
    use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    plan = client.get("/api/mods/update-all", headers=headers).json()
    rows = {row["mod_id"]: row for row in plan["updates"]}
    assert set(rows) == {"alpha", "beta"}
    assert (rows["alpha"]["installed_version"], rows["alpha"]["latest_version"]) == ("1.0", "2.0")
    assert rows["alpha"]["enabled"] is True
    assert rows["beta"]["enabled"] is False
    assert rows["beta"]["filename"] == "beta.jar.disabled"
    assert plan["unchecked"] == []
    assert plan["server_running"] is False
    assert plan["blocked_by"] is None


def test_a_mod_modrinth_could_not_check_is_named_not_left_out(client, mods_dir):
    class Unreachable(FakeModrinth):
        async def latest_for(self, id_or_slug, minecraft_version, loaders=None):
            if id_or_slug == "gamma":
                raise ModrinthError("Modrinth didn't answer.")
            return await super().latest_for(id_or_slug, minecraft_version, loaders)

    use(client, Unreachable(PROJECTS))
    headers = auth(token_for(client))
    plan = client.get("/api/mods/update-all", headers=headers).json()
    assert {row["mod_id"] for row in plan["updates"]} == {"alpha", "beta"}
    assert plan["unchecked"] == [
        {
            "mod_id": "gamma",
            "name": "Gamma",
            "filename": "gamma.jar",
            "reason": "Modrinth didn't answer.",
        }
    ]


def test_update_all_updates_every_ticked_mod_behind_one_backup(client, mods_dir):
    use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    before = len(safety_backups(client, headers))
    plan = client.get("/api/mods/update-all", headers=headers).json()
    body = {
        "mods": [
            {"filename": r["filename"], "version_id": r["version_id"]} for r in plan["updates"]
        ]
    }

    response = client.post("/api/mods/update-all", json=body, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is True
    assert {(u["name"], u["previous_version"], u["version"]) for u in result["updated"]} == {
        ("Alpha", "1.0", "2.0"),
        ("Beta", "1.0", "2.0"),
    }
    # A turned-off mod stays off after its update.
    assert installed(client, headers) == {
        "alpha": ("2.0", True),
        "beta": ("2.0", False),
        "gamma": ("1.0", True),
    }
    made = safety_backups(client, headers)
    assert len(made) == before + 1
    assert made[0]["note"] == "Before Update all"
    assert result["safety_backup"]["name"] == made[0]["name"]
    assert result["undo"]["backup_id"] == made[0]["id"]

    # One task with a step per mod, which an Undo would take back in one go.
    jobs = client.get("/api/jobs", headers=headers).json()["jobs"]
    job = next(j for j in jobs if j["id"] == result["job_id"])
    assert job["state"] == "succeeded"
    assert job["result"]["undo"]["backup_id"] == made[0]["id"]


def test_a_failed_update_puts_every_mod_back_and_names_the_one_that_failed(client, mods_dir):
    use(client, BrokenModrinth(PROJECTS, broken={"beta"}))
    headers = auth(token_for(client))
    body = {"mods": [{"filename": "alpha.jar"}, {"filename": "beta.jar.disabled"}]}
    response = client.post("/api/mods/update-all", json=body, headers=headers)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Beta" in detail and "Modrinth stopped answering." in detail
    assert "put back" in detail
    # Alpha was updated first, then put back with everything else.
    assert installed(client, headers) == {
        "alpha": ("1.0", True),
        "beta": ("1.0", False),
        "gamma": ("1.0", True),
    }
    history = client.get("/api/mods/history", headers=headers).json()["history"]
    assert history[0]["action"] == "update_all" and history[0]["result"] == "failed"


def test_the_plan_saves_what_it_found_for_the_installed_list(client, mods_dir):
    use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    client.get("/api/mods/update-all", headers=headers)
    mods = {m["mod_id"]: m for m in client.get("/api/mods", headers=headers).json()["mods"]}
    assert mods["alpha"]["update_available"]["latest_version"] == "2.0"
    assert mods["beta"]["update_available"]["latest_version"] == "2.0"
    assert mods["gamma"]["update_available"] is None


def test_a_failed_update_all_puts_back_what_the_agent_noted_about_each_mod(client, mods_dir):
    core = use(client, BrokenModrinth(PROJECTS, broken={"beta"}))
    headers = auth(token_for(client))
    client.get("/api/mods/update-all", headers=headers)
    source_before = core.db.get_setting("mod_source:alpha")
    body = {"mods": [{"filename": "alpha.jar"}, {"filename": "beta.jar.disabled"}]}
    assert client.post("/api/mods/update-all", json=body, headers=headers).status_code == 400
    # Alpha is 1.0 again, so its update to 2.0 is still offered.
    mods = {m["mod_id"]: m for m in client.get("/api/mods", headers=headers).json()["mods"]}
    assert mods["alpha"]["version"] == "1.0"
    assert mods["alpha"]["update_available"]["latest_version"] == "2.0"
    assert core.db.get_setting("mod_source:alpha") == source_before


def test_the_same_mod_ticked_twice_is_updated_once(client, mods_dir):
    use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    body = {"mods": [{"filename": "alpha.jar"}, {"filename": "alpha.jar"}]}
    response = client.post("/api/mods/update-all", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert [u["name"] for u in response.json()["updated"]] == ["Alpha"]


def test_update_all_is_refused_while_the_server_runs(client, mods_dir):
    core = use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    assert client.post("/api/server/start", headers=headers).status_code == 200
    deadline = time.time() + 20
    while core.server.state.value != "ONLINE" and time.time() < deadline:
        time.sleep(0.1)
    try:
        plan = client.get("/api/mods/update-all", headers=headers).json()
        assert plan["server_running"] is True
        response = client.post(
            "/api/mods/update-all", json={"mods": [{"filename": "alpha.jar"}]}, headers=headers
        )
        assert response.status_code == 400
        assert "Stop it before" in response.json()["detail"]
    finally:
        client.post("/api/server/stop", headers=headers)
    assert installed(client, headers)["alpha"] == ("1.0", True)


def test_update_all_waits_for_another_task_holding_the_server(client, mods_dir):
    core = use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    core.server.held_by = "Restoring manual-1.zip"
    try:
        assert client.get("/api/mods/update-all", headers=headers).json()["blocked_by"] == (
            "Restoring manual-1.zip"
        )
        response = client.post(
            "/api/mods/update-all", json={"mods": [{"filename": "alpha.jar"}]}, headers=headers
        )
        assert response.status_code == 409
        assert "Restoring manual-1.zip" in response.json()["detail"]
    finally:
        core.server.held_by = None


def test_update_all_needs_a_mod_and_one_that_is_installed(client, mods_dir):
    use(client, FakeModrinth(PROJECTS))
    headers = auth(token_for(client))
    assert (
        client.post("/api/mods/update-all", json={"mods": []}, headers=headers).status_code == 422
    )
    missing = client.post(
        "/api/mods/update-all", json={"mods": [{"filename": "nothing.jar"}]}, headers=headers
    )
    assert missing.status_code == 400
    assert "nothing.jar" in missing.json()["detail"]


def test_a_helper_sees_the_plan_but_cannot_update_all(multi_client):
    owner = dict(multi_client.headers)
    helper = add_helper(multi_client, owner)
    path = "/api/servers/survival/mods/update-all"
    multi_client.app.state.core.get_server("survival").mods.modrinth = FakeModrinth(PROJECTS)
    assert multi_client.get(path, headers=helper).status_code == 200
    refused = multi_client.post(path, json={"mods": [{"filename": "alpha.jar"}]}, headers=helper)
    assert refused.status_code == 403


# ------------------------------------------------------------ typed answers
def test_the_installed_list_and_one_mods_changes_answer_in_their_typed_shapes(
    client, mods_dir, tmp_path
):
    use(
        client,
        FakeModrinth(
            {
                **PROJECTS,
                "delta": {"project_id": "DELTA001", "title": "Delta", "versions": [("1.5", [])]},
            }
        ),
    )
    headers = auth(token_for(client))

    listed = client.get("/api/mods", headers=headers).json()
    assert listed["server_state"] == "OFFLINE"
    alpha = next(m for m in listed["mods"] if m["mod_id"] == "alpha")
    assert alpha["status"] == "ok" and alpha["issues"] == [] and alpha["update_available"] is None

    off = client.post("/api/mods/disable", json={"filename": "alpha.jar"}, headers=headers).json()
    assert off["ok"] is True and off["mod"]["enabled"] is False
    on = client.post("/api/mods/enable", json={"filename": "alpha.jar.disabled"}, headers=headers)
    assert on.json()["mod"]["filename"] == "alpha.jar"

    impact = client.get("/api/mods/impact?filename=gamma.jar", headers=headers).json()
    assert impact["dependents"] == []
    removed = client.post(
        "/api/mods/remove", json={"filename": "gamma.jar"}, headers=headers
    ).json()
    assert removed["ok"] is True and removed["trash"]

    updated = client.post(
        "/api/mods/update", json={"filename": "alpha.jar"}, headers=headers
    ).json()
    assert (updated["previous_version"], updated["updated"]["version"]) == ("1.0", "2.0")
    versions = client.get("/api/mods/versions/alpha", headers=headers).json()["versions"]
    old = next(v for v in versions if v["version"] == "1.0")
    assert old["exists"] is True and old["is_current"] is False
    back = client.post(
        "/api/mods/rollback",
        json={"mod_id": "alpha", "archive_path": old["archive_path"]},
        headers=headers,
    ).json()
    assert (back["previous_version"], back["restored"]["version"]) == ("2.0", "1.0")

    history = client.get("/api/mods/history", headers=headers).json()["history"]
    assert [h["action"] for h in history[:2]] == ["rollback", "update"]
    assert history[0]["result"] == "ok"

    found = client.get("/api/mods/search?q=delta", headers=headers).json()
    assert [hit["slug"] for hit in found["hits"]] == ["delta"]
    project = client.get("/api/mods/project/delta", headers=headers).json()
    assert project["project"]["title"] == "Delta"
    assert project["versions"][0]["file"]["filename"] == "delta-1.5.jar"
    installed_now = client.post("/api/mods/install", json={"project": "delta"}, headers=headers)
    assert installed_now.status_code == 200, installed_now.text
    assert installed_now.json()["installed"]["version"] == "1.5"

    jar = make_jar(tmp_path / "epsilon.jar", "epsilon", version="3.0", name="Epsilon")
    added = client.post(
        "/api/mods/upload",
        files={"file": ("epsilon.jar", jar.read_bytes(), "application/java-archive")},
        headers=headers,
    ).json()
    assert added["ok"] is True and added["installed"]["mod_id"] == "epsilon"


def test_missing_dependencies_are_listed_planned_and_installed(client, mods_dir):
    make_jar(mods_dir / "needs.jar", "needs", depends={"cloud": "*"})
    use(
        client,
        FakeModrinth(
            {"cloud": {"project_id": "CLOUD001", "title": "Cloud", "versions": [("2.0", [])]}}
        ),
    )
    headers = auth(token_for(client))
    report = client.get("/api/mods/dependencies", headers=headers).json()
    assert report["missing_required"] == ["cloud"]
    plan = client.post("/api/mods/dependencies/plan", json={}, headers=headers).json()
    assert [(i["title"], i["version_number"]) for i in plan["items"]] == [("Cloud", "2.0")]
    assert plan["unresolvable"] == []
    done = client.post("/api/mods/dependencies/install", json={}, headers=headers).json()
    assert done["results"][0]["result"] == "installed" and done["still_missing"] == []


def test_a_modpack_imported_into_a_server_answers_its_typed_shape(
    multi_client, tmp_path, monkeypatch
):
    from agent import modpack

    from .test_modpack import make_pack

    data = make_pack(tmp_path / "p.mrpack").read_bytes()
    inspected = multi_client.post(
        "/api/modpacks/inspect?server_id=survival",
        files={"file": ("p.mrpack", data, "application/zip")},
    ).json()
    assert inspected["pack"]["can_import"] is True
    assert {f["status"] for f in inspected["pack"]["files"]} == {"download", "client_only"}

    async def imported(ctx, token, user="system"):
        return {
            "job_id": "j1",
            "modpack": {"name": "Test Pack", "downloaded": 1, "check": "1 file checked"},
            "moved_aside": [],
            "version_change": True,
            "undo": {"kind": "restore_backup", "backup_id": 3, "backup": "pre-modpack.zip"},
        }

    monkeypatch.setattr(modpack, "import_into", imported)
    response = multi_client.post(
        "/api/servers/survival/modpack", json={"token": inspected["token"], "confirm": True}
    )
    assert response.status_code == 200, response.text
    assert response.json()["undo"]["backup_id"] == 3


def test_game_settings_answer_their_typed_shape(client):
    headers = auth(token_for(client))
    view = client.get("/api/servers/test/game-settings", headers=headers).json()
    fields = {f["key"]: f for f in view["fields"]}
    assert fields["max-players"]["value"] == 20 and fields["max-players"]["set"] is True
    assert (
        fields["difficulty"]["set"] is False and fields["difficulty"]["minecraft_default"] == "easy"
    )
    assert fields["level-seed"]["read_only"] == "world_exists"
    assert view["running"] is False and view["restart_needed"] is False

    saved = client.put(
        "/api/servers/test/game-settings", json={"values": {"difficulty": "hard"}}, headers=headers
    ).json()
    assert saved["ok"] is True and saved["keys"] == ["difficulty"]
    assert saved["safety_backup"] and saved["undo"]["kind"] == "restore_backup"
    again = client.put(
        "/api/servers/test/game-settings", json={"values": {"difficulty": "hard"}}, headers=headers
    )
    assert again.json()["nothing_changed"] is True

    taken = client.put(
        "/api/servers/test/game-settings", json={"values": {"server-port": 80}}, headers=headers
    )
    assert taken.status_code == 400 and "server-port" in taken.json()["problems"]
