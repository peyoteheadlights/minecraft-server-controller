"""Dependency analysis, planning and installation.

Modrinth is replaced by a fake whose downloads are real jar files, so the
install path runs end to end through the real ModManager: path checks,
duplicate refusal, archiving and history.
"""

import hashlib
import io
import json
import zipfile

import pytest

from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.process import MinecraftServer
from agent.mods.dependencies import describe_range, valid_identifier
from agent.mods.manager import ModError, ModManager
from agent.mods.modrinth import ModrinthNotFound

from .test_mods import make_jar


def jar_bytes(mod_id, version, depends=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": mod_id,
                    "version": version,
                    "name": mod_id.title(),
                    "depends": depends or {},
                }
            ),
        )
    return buffer.getvalue()


class FakeModrinth:
    """projects: slug -> dict(project_id, title, versions=[(number, [dep project ids], filename?)])"""

    def __init__(self, projects, mc="1.21.1"):
        self.projects = projects
        self.mc = mc
        self.downloads = []
        self.by_id = {p["project_id"]: slug for slug, p in projects.items()}

    def _info(self, slug):
        p = self.projects[slug]
        return {
            "project_id": p["project_id"],
            "slug": slug,
            "title": p["title"],
            "page": f"https://modrinth.com/mod/{slug}",
        }

    async def project(self, id_or_slug):
        slug = self.by_id.get(id_or_slug, id_or_slug)
        if slug not in self.projects:
            raise ModrinthNotFound("Modrinth doesn't have that.")
        return self._info(slug)

    async def search(self, query, minecraft_version=None, limit=10, offset=0):
        hits = [dict(self._info(s)) for s in self.projects if query.lower() in s]
        return {"hits": hits, "total": len(hits)}

    def _version(self, slug, number, deps, filename=None):
        return {
            "version_id": f"{slug}-{number}",
            "project_id": self.projects[slug]["project_id"],
            "version_number": number,
            "release_type": "release",
            "game_versions": [self.mc],
            "loaders": ["fabric"],
            "dependencies": [{"project_id": d, "type": "required"} for d in deps],
            "file": {
                "filename": filename or f"{slug}-{number}.jar",
                "size": 1234,
                "url": f"https://cdn.modrinth.com/{slug}.jar",
                "sha512": "x",
            },
        }

    async def versions(self, id_or_slug, minecraft_version=None, loaders=None):
        slug = self.by_id.get(id_or_slug, id_or_slug)
        return [self._version(slug, *v) for v in self.projects[slug]["versions"]]

    async def version(self, version_id):
        for slug in self.projects:
            for v in await self.versions(slug):
                if v["version_id"] == version_id:
                    return v
        raise ModrinthNotFound("Modrinth doesn't have that.")

    async def latest_for(self, id_or_slug, minecraft_version, loaders=None):
        return (await self.versions(id_or_slug))[0]

    async def download(self, version):
        slug = self.by_id[version["project_id"]]
        self.downloads.append(slug)
        data = jar_bytes(self.projects[slug].get("mod_id", slug), version["version_number"])
        return data, version["file"]["filename"], hashlib.sha256(data).hexdigest()

    async def close(self):
        pass


@pytest.fixture
def mods(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    server.mc_version = "1.21.1"
    server.loader_version = "0.16.5"
    return ModManager(config, bus, db, server)


def use(mods, projects):
    fake = FakeModrinth(projects)
    mods.modrinth = fake
    return fake


def item(report, mod_id):
    return next(i for i in report["items"] if i["mod_id"] == mod_id)


# ---------------------------------------------------------------- readable output
@pytest.mark.parametrize(
    "spec,words",
    [
        ("*", "Any version"),
        ("", "Any version"),
        (">=1.2.0", "1.2.0 or newer"),
        ("<2", "older than 2"),
        ("1.4.x", "any 1.4 release"),
        ("=3.1", "exactly 3.1"),
        (">=1.0 <2.0", "1.0 or newer and older than 2.0"),
        ("~1.2.3", "1.2.3 or a newer 1.2.x release"),
        ("^2.1", "2.1 or a newer 2.x release"),
        (">=1 || >=3", "1 or newer or 3 or newer"),
    ],
)
def test_version_ranges_read_as_words(spec, words):
    assert describe_range(spec) == words


def test_the_skinsrestorer_case_is_understandable(mods, config):
    """The exact message the user found cryptic: 'SkinsRestorer requires cloud *'."""
    make_jar(
        config.mods_dir / "skinsrestorer.jar",
        "skinsrestorer",
        "15.0",
        name="SkinsRestorer",
        depends={"cloud": "*"},
    )
    report = mods.deps.analyse()
    dep = item(report, "cloud")
    assert dep["status"] == "missing"
    assert dep["kind"] == "required"
    assert dep["name"] == "Cloud"
    assert dep["range_text"] == "Any version"
    assert dep["required_by"][0]["name"] == "SkinsRestorer"
    detail = next(
        p["detail"] for p in mods.check_all()["problems"] if p["kind"] == "missing_dependency"
    )
    assert "*" not in detail and "Any version" in detail


# ---------------------------------------------------------------- analysis
def test_a_compatible_dependency_is_satisfied(mods, config):
    make_jar(config.mods_dir / "a.jar", "moda", depends={"lib": ">=1.0"})
    make_jar(config.mods_dir / "lib.jar", "lib", "1.4")
    assert item(mods.deps.analyse(), "lib")["status"] == "satisfied"


def test_an_incompatible_version_is_reported_not_replaced(mods, config):
    make_jar(config.mods_dir / "a.jar", "moda", depends={"lib": ">=2.0"})
    make_jar(config.mods_dir / "lib.jar", "lib", "1.4")
    dep = item(mods.deps.analyse(), "lib")
    assert dep["status"] == "incompatible"
    assert "wasn't replaced automatically" in dep["reason"]
    assert dep["installed_version"] == "1.4"


def test_an_optional_dependency_is_listed_but_not_required(mods, config):
    path = config.mods_dir / "a.jar"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "fabric.mod.json",
            json.dumps(
                {"schemaVersion": 1, "id": "moda", "version": "1", "recommends": {"extras": "*"}}
            ),
        )
    report = mods.deps.analyse()
    assert item(report, "extras")["kind"] == "optional"
    assert "extras" not in report["missing_required"]


def test_a_disabled_dependency_is_distinguished_from_missing(mods, config):
    make_jar(config.mods_dir / "a.jar", "moda", depends={"lib": "*"})
    make_jar(config.mods_dir / "lib.jar.disabled", "lib", "1.0")
    assert item(mods.deps.analyse(), "lib")["status"] == "disabled"


def test_minecraft_version_is_checked_as_a_platform_requirement(mods, config):
    make_jar(config.mods_dir / "a.jar", "moda", depends={"minecraft": ">=1.22"})
    dep = item(mods.deps.analyse(), "minecraft")
    assert dep["status"] == "platform_incompatible"
    assert "1.21.1" in dep["reason"]


async def test_modrinth_supplies_the_readable_name(mods, config):
    make_jar(config.mods_dir / "a.jar", "moda", depends={"cloud": "*"})
    use(
        mods,
        {
            "cloud": {
                "project_id": "CLOUD001",
                "title": "Cloud Command Framework",
                "versions": [("2.0", [])],
            }
        },
    )
    report = await mods.deps.describe(mods.deps.analyse())
    dep = item(report, "cloud")
    assert dep["name"] == "Cloud Command Framework"
    assert dep["modrinth"]["page"] == "https://modrinth.com/mod/cloud"


# ---------------------------------------------------------------- planning and installing
NESTED = {
    "mod-b": {"project_id": "MODB0001", "title": "Mod B", "versions": [("1.0", ["MODC0001"])]},
    "mod-c": {"project_id": "MODC0001", "title": "Mod C", "versions": [("3.2", [])]},
}


async def test_nested_dependencies_are_planned_before_anything_downloads(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"mod-b": "*"})
    fake = use(mods, NESTED)
    plan = await mods.deps.plan()
    assert [i["slug"] for i in plan["items"]] == ["mod-c", "mod-b"], "deepest first"
    assert fake.downloads == [], "planning must not download"
    assert plan["items"][0]["required_by"] == ["Mod B"]


async def test_nested_dependencies_install_and_resolve(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"mod-b": "*"})
    fake = use(mods, NESTED)
    result = await mods.deps.install(None, user="tester")
    assert [r["result"] for r in result["results"]] == ["installed", "installed"]
    assert fake.downloads == ["mod-c", "mod-b"]
    assert result["still_missing"] == []
    assert (config.mods_dir / "mod-b-1.0.jar").is_file()
    assert (config.mods_dir / "mod-c-3.2.jar").is_file()
    assert any(h["action"] == "install" for h in mods.history())


async def test_a_dependency_shared_by_two_mods_is_downloaded_once(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"mod-c": "*"})
    make_jar(config.mods_dir / "x.jar", "mod-x", depends={"mod-c": ">=3.0"})
    fake = use(mods, NESTED)
    plan = await mods.deps.plan()
    assert len(plan["items"]) == 1
    assert sorted(plan["items"][0]["required_by"]) == ["Mod-A", "Mod-X"]
    await mods.deps.install(None, user="tester")
    assert fake.downloads == ["mod-c"]


async def test_an_installed_dependency_is_never_downloaded_again(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"mod-b": "*"})
    make_jar(config.mods_dir / "mod-c.jar", "mod-c", "9.0")  # newer than Modrinth offers
    fake = use(mods, NESTED)
    plan = await mods.deps.plan()
    assert [i["slug"] for i in plan["items"]] == ["mod-b"]
    assert plan["skipped"][0]["reason"] == "Already installed"
    await mods.deps.install(None, user="tester")
    assert "mod-c" not in fake.downloads
    assert (config.mods_dir / "mod-c.jar").is_file(), "the existing newer jar is kept"


async def test_a_version_satisfying_the_range_is_chosen(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"lib": "<2.0"})
    use(
        mods,
        {
            "lib": {
                "project_id": "LIB00001",
                "title": "Lib",
                "versions": [("2.5", []), ("1.9", []), ("1.0", [])],
            }
        },
    )
    plan = await mods.deps.plan()
    assert plan["items"][0]["version_number"] == "1.9"
    assert plan["items"][0]["range_verified"] is True


async def test_no_satisfying_version_is_explained(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"lib": ">=5.0"})
    use(mods, {"lib": {"project_id": "LIB00001", "title": "Lib", "versions": [("2.5", [])]}})
    plan = await mods.deps.plan()
    assert plan["items"] == []
    assert "5.0 or newer" in plan["unresolvable"][0]["reason"]


async def test_a_dependency_missing_from_modrinth_is_explained(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"secret-lib": "*"})
    use(mods, {})
    plan = await mods.deps.plan()
    assert plan["unresolvable"][0]["reason"] == "Not found on Modrinth. Install it manually."


async def test_malicious_identifiers_are_refused(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"../../evil": "*"})
    use(mods, {})
    plan = await mods.deps.plan()
    assert plan["items"] == []
    assert "not a valid mod identifier" in plan["unresolvable"][0]["reason"]
    for bad in ("../x", "a/b", "x\\y", "a b", "", "https://evil"):
        assert not valid_identifier(bad)


async def test_a_traversal_filename_from_modrinth_writes_nothing(mods, config, tmp_path):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"evil": "*"})
    use(
        mods,
        {
            "evil": {
                "project_id": "EVIL0001",
                "title": "Evil",
                "versions": [("1.0", [], "../../escaped.jar")],
            }
        },
    )
    result = await mods.deps.install(None, user="tester")
    assert result["results"][0]["result"] == "failed"
    assert not list(tmp_path.rglob("escaped.jar"))


async def test_installing_is_refused_while_the_server_runs(mods, config):
    make_jar(config.mods_dir / "a.jar", "mod-a", depends={"mod-b": "*"})
    use(mods, NESTED)
    await mods.server.start()
    await mods.server.wait_online(timeout=20)
    try:
        with pytest.raises(ModError, match="Stop it before"):
            await mods.deps.install(None, user="tester")
    finally:
        await mods.server.stop()


def test_dependency_endpoints(config, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    monkeypatch.setenv(
        "MCSC_ADMIN_PASSWORD_HASH", hash_password("long enough password", rounds=1000)
    )
    make_jar(
        config.mods_dir / "skinsrestorer.jar",
        "skinsrestorer",
        name="SkinsRestorer",
        depends={"cloud": "*"},
    )
    with TestClient(create_app(config)) as client:
        core = client.app.state.core
        core.server.mc_version = "1.21.1"
        core.mods.modrinth = FakeModrinth(
            {"cloud": {"project_id": "CLOUD001", "title": "Cloud", "versions": [("2.0", [])]}}
        )
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": "long enough password"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        report = client.get("/api/mods/dependencies", headers=headers).json()
        cloud = item(report, "cloud")
        assert (cloud["name"], cloud["range_text"], cloud["status"]) == (
            "Cloud",
            "Any version",
            "missing",
        )
        plan = client.post("/api/mods/dependencies/plan", headers=headers, json={}).json()
        assert plan["items"][0]["title"] == "Cloud"
        installed = client.post("/api/mods/dependencies/install", headers=headers, json={}).json()
        assert installed["results"][0]["result"] == "installed"
        assert (
            client.post(
                "/api/mods/dependencies/plan", headers=headers, json={"mod_ids": ["../x"]}
            ).status_code
            == 400
        )
