"""Phase 8: Bedrock Dedicated Server as a server type of its own.

The console patterns are checked against real server output
(fixtures/bedrock_console.txt); the running-server tests use a fake
Bedrock server (fixtures/fake_bedrock_server.py) that prints the same lines
and keeps the same files. Nothing here touches the network: downloads go
to an httpx MockTransport that records every request.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import struct
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest

from agent import addons, downloads, servertypes, worldimport
from agent.backups import hold
from agent.core import AgentCore
from agent.minecraft import nbt, playeractions, properties, raknet
from agent.minecraft.console import ConsoleLine, extract_signals, parse_line
from agent.minecraft.process import MinecraftServer
from agent.servertypes import bedrock
from agent.servertypes import install as install_module
from agent.servertypes import versions as versions_module
from agent.servertypes.create import create_server, options
from agent.servertypes.install import InstallError

from .conftest import FAKE_BEDROCK, PASSWORD, build_bedrock_config, build_multi_config
from .test_multi_server import wait_for

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "bedrock_console.txt"
LATEST = "1.21.95.1"
ZIP_URL = f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{LATEST}.zip"


def sample_lines() -> list[ConsoleLine]:
    raw = [
        ln
        for ln in SAMPLE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    return [parse_line(text, number, "stdout") for number, text in enumerate(raw, 1)]


# ====================================================================
# the console
# ====================================================================
def test_real_bedrock_lines_are_read():
    lines = sample_lines()
    signals = [extract_signals(line, "bedrock") for line in lines]
    assert [s.mc_version for s in signals if s.mc_version] == ["1.21.95.1", "1.14.60.5"]
    assert sum(1 for s in signals if s.started) == 1
    assert [s.port for s in signals if s.port] == [19132, 19132]
    joins = [s.player_joined for s in signals if s.player_joined]
    assert joins == ["fooBarBazz"]
    assert [s.player_uuid for s in signals if s.player_uuid] == [("fooBarBazz", "2533274474361790")]
    assert [s.player_left for s in signals if s.player_left] == ["mjwrazor"]
    # The timestamp and level are taken off, as for Java lines.
    assert lines[0].message == "Starting Server" and lines[0].level == "INFO"


def test_bedrock_patterns_dont_fire_on_java_servers():
    started = parse_line("[2025-07-15 16:33:55:972 INFO] Server started.", 1, "stdout")
    assert extract_signals(started, "bedrock").started
    assert not extract_signals(started, "java").started


def test_a_disconnect_with_a_pfid_and_a_name_with_spaces_is_read():
    line = parse_line(
        "[2025-07-15 16:40:00:001 INFO] Player disconnected: Big Steve, xuid: 25, pfid: abc",
        1,
        "stdout",
    )
    assert extract_signals(line, "bedrock").player_left == "Big Steve"


def test_a_player_typing_a_join_line_in_chat_isnt_a_join():
    # Bedrock doesn't print chat, but a console line that isn't stdout from
    # the server (the agent's own echo) is never read as a signal.
    line = parse_line("Player connected: Fake, xuid: 1", 1, "stdin")
    assert extract_signals(line, "bedrock").player_joined is None


# ====================================================================
# the catalog: what doesn't apply is said, not hidden behind a control
# ====================================================================
def test_bedrock_declares_what_doesnt_apply():
    entry = {t["id"]: t for t in servertypes.catalog()}["bedrock"]
    assert entry["edition"] == "bedrock"
    assert entry["takes_memory_limit"] is False
    assert entry["reports_speed"] is False
    assert entry["crossplay"] is False
    assert entry["reads_chat"] is False
    assert entry["bans"] is False
    assert entry["addons"] is True
    assert entry["game_protocol"] == "udp"
    assert entry["latest_only"] is True
    assert entry["modrinth"] is False


def test_java_and_bedrock_cant_be_changed_into_each_other():
    java, bedrock_type = servertypes.get("paper"), servertypes.get("bedrock")
    assert not java.can_change_to(bedrock_type) and not bedrock_type.can_change_to(java)
    with pytest.raises(InstallError, match="Create a new server instead"):
        install_module.refuse_other_edition(java, bedrock_type)
    with pytest.raises(InstallError, match="Create a new server instead"):
        install_module.refuse_other_edition(bedrock_type, java)


def test_the_launch_command_is_mojangs_program_and_nothing_else(tmp_path):
    from agent.events import EventBus

    config = build_bedrock_config(tmp_path)
    view = config.for_server("bedrock")
    view.set("server.raw_command", [])
    server = MinecraftServer(view, EventBus())
    command = server.build_command()
    assert command == [str(view.server_dir / "bedrock_server.exe")]
    assert server.launch_problem() is None


@pytest.mark.parametrize("name", ["cmd.exe", "../bedrock_server.exe", "x/bedrock_server.exe"])
def test_another_program_name_is_refused(tmp_path, name):
    from agent.events import EventBus

    view = build_bedrock_config(tmp_path).for_server("bedrock")
    view.set("server.raw_command", [])
    view.set("server.jar", name)
    problem = MinecraftServer(view, EventBus()).launch_problem()
    assert problem and "wasn't started" in problem


# ====================================================================
# a running Bedrock server
# ====================================================================
@pytest.fixture
async def running(tmp_path):
    core = AgentCore(build_bedrock_config(tmp_path))
    ctx = core.servers["bedrock"]
    await ctx.start()
    await ctx.server.start()
    assert await ctx.server.wait_online(20)
    try:
        yield ctx
    finally:
        if ctx.server.running:
            await ctx.server.stop()
        await ctx.stop()
        await core.jobs.stop()
        core.db.close()


async def test_the_server_counts_as_online_when_it_says_server_started(running):
    status = running.server.status()
    assert status["state"] == "ONLINE"
    assert status["minecraft_version"] == LATEST
    assert running.server.detected_port == 19132


async def test_players_are_tracked_by_xuid(running):
    await running.server.send_command("fakejoin Big Steve 2533274474361790", internal=True)
    assert await wait_for(lambda: running.players.online_count() == 1, 10)
    assert running.players.names_by_id().get("2533274474361790") == "Big Steve"
    await running.server.send_command("list", internal=True)
    assert await wait_for(lambda: running.players.verified, 10)
    assert [p["username"] for p in running.players.online()] == ["Big Steve"]
    await running.server.send_command("fakeleave Big Steve", internal=True)
    assert await wait_for(lambda: running.players.online_count() == 0, 10)


async def test_allowlist_and_operator_buttons_use_bedrocks_commands(running):
    pending = await running.player_actions.send("whitelist_add", "Big Steve")
    assert pending.command == 'allowlist add "Big Steve"'
    assert await wait_for(lambda: running.player_actions.get(pending.id).state == "done", 10)
    lists = playeractions.lists(running.config.server_dir, "bedrock", {})
    assert [p["name"] for p in lists["whitelist"]["players"]] == ["Big Steve"]
    assert lists["banned"]["not_applicable"] is True

    await running.server.send_command("fakejoin Alex 2535409695687979", internal=True)
    assert await wait_for(lambda: running.players.online_count() == 1, 10)
    op = await running.player_actions.send("op", "Alex")
    assert await wait_for(lambda: running.player_actions.get(op.id).state == "done", 10)
    lists = playeractions.lists(running.config.server_dir, "bedrock", running.players.names_by_id())
    assert lists["ops"]["players"] == [{"name": "Alex", "uuid": "2535409695687979", "level": None}]


async def test_ban_is_refused_on_bedrock(running):
    with pytest.raises(playeractions.PlayerActionError, match="no ban list"):
        await running.player_actions.send("ban", "Alex")


async def test_speed_is_not_available_for_bedrock(running):
    assert running.tps.mode() == "unsupported"
    assert running.tps.status_data["state"] == "unavailable"
    assert running.tps.status_data["message"].startswith("Not available for Bedrock servers")


# ====================================================================
# backups: save hold, save query, copy, save resume
# ====================================================================
def test_the_file_list_is_read_and_must_stay_inside_worlds():
    found = hold.parse_files("Bedrock level/db/000005.ldb:1234, Bedrock level/level.dat:2386")
    assert found == [("Bedrock level/db/000005.ldb", 1234), ("Bedrock level/level.dat", 2386)]
    with pytest.raises(hold.HoldError, match="outside"):
        hold.parse_files("../server.properties:10")
    with pytest.raises(hold.HoldError):
        hold.parse_files("not a list")


def test_each_file_is_cut_to_its_listed_length(tmp_path):
    source = tmp_path / "a.ldb"
    source.write_bytes(b"0123456789")
    hold.copy_truncated(source, tmp_path / "out" / "a.ldb", 4)
    assert (tmp_path / "out" / "a.ldb").read_bytes() == b"0123"
    with pytest.raises(hold.HoldError, match="shorter"):
        hold.copy_truncated(source, tmp_path / "b.ldb", 50)


def record_commands(ctx) -> list[str]:
    """Every command the agent sends this server from now on."""
    sent: list[str] = []
    real = ctx.server.send_command

    async def send(command, internal=False):
        sent.append(command)
        return await real(command, internal=internal)

    ctx.server.send_command = send
    return sent


async def test_a_running_server_is_backed_up_under_save_hold(running):
    world = running.config.server_dir / "worlds" / "Bedrock level"
    sent = record_commands(running)
    result = await running.backups.create(name="held")
    assert result["verified"] is True
    assert "save hold" in sent and "save resume" in sent
    assert sent.index("save hold") < sent.index("save resume")
    assert sent.count("save query") >= 2  # not ready the first time
    with zipfile.ZipFile(result["path"]) as zf:
        names = set(zf.namelist())
        assert "worlds/Bedrock level/level.dat" in names
        assert "worlds/Bedrock level/db/000005.ldb" in names
        assert (
            zf.read("worlds/Bedrock level/db/000005.ldb")
            == (world / "db" / "000005.ldb").read_bytes()
        )
        assert "server.properties" in names and "allowlist.json" in names
    row = running.backups.get(result["id"])
    assert "worlds" in row["includes"].split(",")


async def test_save_resume_is_sent_even_when_the_copy_fails(running, monkeypatch):
    def broken(source, target, length):
        raise OSError("disk full")

    monkeypatch.setattr(hold, "copy_truncated", broken)
    sent = record_commands(running)
    with pytest.raises(Exception, match="disk full"):
        await running.backups.create(name="broken")
    assert sent[-1] == "save resume"
    assert await wait_for(
        lambda: any(
            "Changes to the world are resumed" in line.raw
            for line in running.server.console.since(0, 5000)
        ),
        10,
    )
    assert not list(running.backups.directory.glob("mcsc-hold-*")), "staging is cleaned up"


async def test_save_resume_is_sent_when_the_server_never_gets_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SAVE_QUERY", "never")
    core = AgentCore(build_bedrock_config(tmp_path))
    ctx = core.servers["bedrock"]
    await ctx.start()
    await ctx.server.start()
    assert await ctx.server.wait_online(20)
    try:
        sent = record_commands(ctx)
        with pytest.raises(hold.HoldError, match="didn't say"):
            await hold.copy_world(
                ctx.server,
                ctx.config.server_dir / "worlds",
                tmp_path / "staging",
                wait=1.5,
                poll=0.3,
            )
        assert sent[-1] == "save resume"
    finally:
        await ctx.server.stop()
        await ctx.stop()
        await core.jobs.stop()
        core.db.close()


async def test_a_listed_path_outside_worlds_stops_the_copy_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SAVE_QUERY", "outside")
    core = AgentCore(build_bedrock_config(tmp_path))
    ctx = core.servers["bedrock"]
    await ctx.start()
    await ctx.server.start()
    assert await ctx.server.wait_online(20)
    try:
        sent = record_commands(ctx)
        with pytest.raises(hold.HoldError, match="outside"):
            await hold.copy_world(
                ctx.server, ctx.config.server_dir / "worlds", tmp_path / "staging", poll=0.3
            )
        assert sent[-1] == "save resume"
        assert not (tmp_path / "staging" / "server.properties").exists()
    finally:
        await ctx.server.stop()
        await ctx.stop()
        await core.jobs.stop()
        core.db.close()


async def test_a_stopped_server_is_copied_directly(tmp_path):
    core = AgentCore(build_bedrock_config(tmp_path))
    ctx = core.servers["bedrock"]
    try:
        result = await ctx.backups.create(name="stopped")
        assert result["verified"] is True
        with zipfile.ZipFile(result["path"]) as zf:
            assert "worlds/Bedrock level/level.dat" in zf.namelist()
    finally:
        await core.jobs.stop()
        core.db.close()


# ====================================================================
# add-ons
# ====================================================================
def manifest(kind="data", **header) -> dict:
    head = {
        "name": "Better Mobs",
        "description": "Mobs, but better",
        "uuid": str(uuid.uuid4()),
        "version": [1, 2, 0],
        **header,
    }
    return {
        "format_version": 2,
        "header": head,
        "modules": [{"type": kind, "uuid": str(uuid.uuid4()), "version": [1, 2, 0]}],
    }


def pack_zip(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def mcpack(data: dict | str, extra: dict | None = None) -> bytes:
    text = data if isinstance(data, str) else json.dumps(data)
    return pack_zip({"manifest.json": text, "pack_icon.png": b"png", **(extra or {})})


def test_a_valid_manifest_is_read():
    info = addons.read_manifest(json.dumps(manifest("resources")).encode())
    assert info["kind"] == "resource" and info["version"] == "1.2.0"
    assert info["name"] == "Better Mobs"


def test_mojangs_comments_are_allowed_in_a_manifest():
    text = "// made by hand\n" + json.dumps(manifest()) + "\n/* end */"
    assert addons.read_manifest(text.encode())["kind"] == "behavior"


@pytest.mark.parametrize(
    "broken, message",
    [
        ("not json", "isn't valid JSON"),
        ({"modules": []}, "no header"),
        ({"header": {"uuid": "nope", "version": [1, 0, 0]}, "modules": []}, "valid UUID"),
        ({"header": {"uuid": str(uuid.uuid4()), "version": "one"}, "modules": []}, "valid version"),
        (
            {"header": {"uuid": str(uuid.uuid4()), "version": [1, 0]}, "modules": []},
            "valid version",
        ),
        (
            {"header": {"uuid": str(uuid.uuid4()), "version": [1, 0, 0]}, "modules": []},
            "no modules",
        ),
    ],
)
def test_a_bad_manifest_is_refused(broken, message):
    text = broken if isinstance(broken, str) else json.dumps(broken)
    with pytest.raises(addons.AddonError, match=message):
        addons.read_manifest(text.encode())


def test_skin_packs_and_mixed_packs_are_refused():
    with pytest.raises(addons.AddonError, match="skin pack"):
        addons.read_manifest(json.dumps(manifest("skin_pack")).encode())
    mixed = manifest()
    mixed["modules"].append({"type": "resources", "uuid": str(uuid.uuid4()), "version": [1, 0, 0]})
    with pytest.raises(addons.AddonError, match="mixes"):
        addons.read_manifest(json.dumps(mixed).encode())


@pytest.mark.parametrize("evil", ["../evil.js", "/etc/evil", "C:/evil.txt", "a/../../evil"])
def test_a_zip_slip_path_refuses_the_whole_pack(evil):
    data = mcpack(manifest(), {evil: b"x"})
    with pytest.raises(addons.AddonError, match="isn't safe"):
        addons.read_upload("evil.mcpack", data)


def test_only_bedrock_add_on_files_are_read():
    with pytest.raises(addons.AddonError, match=".mcpack"):
        addons.read_upload("mod.jar", mcpack(manifest()))
    with pytest.raises(addons.AddonError, match="isn't a zip"):
        addons.read_upload("x.mcpack", b"not a zip")


def test_an_mcaddon_holds_several_packs():
    behavior = mcpack(manifest("data", name="Behaviour"))
    resource = mcpack(manifest("resources", name="Textures"))
    data = pack_zip({"Behaviour.mcpack": behavior, "Textures.mcpack": resource})
    found = addons.read_upload("bundle.mcaddon", data)
    assert sorted(f.manifest["kind"] for f in found) == ["behavior", "resource"]


async def test_a_pack_is_installed_and_turned_on_in_the_world(tmp_path):
    core = AgentCore(build_bedrock_config(tmp_path))
    ctx = core.servers["bedrock"]
    try:
        data = manifest("data")
        result = addons.install(ctx, "mobs.mcpack", mcpack(data))
        installed = result["installed"][0]
        assert installed["enabled"] is True
        assert installed["folder"].startswith("behavior_packs/Better_Mobs_")
        folder = ctx.config.server_dir / installed["folder"]
        assert (folder / "manifest.json").is_file() and (folder / "pack_icon.png").is_file()
        world = ctx.config.server_dir / "worlds" / "Bedrock level"
        entries = json.loads((world / "world_behavior_packs.json").read_text())
        assert entries == [{"pack_id": data["header"]["uuid"], "version": [1, 2, 0]}]
        # Mojang's own packs aren't listed as add-ons someone added.
        assert [p.uuid for p in addons.list_packs(ctx)] == [data["header"]["uuid"]]

        addons.set_enabled(ctx, data["header"]["uuid"], False)
        assert json.loads((world / "world_behavior_packs.json").read_text()) == []
        removed = addons.remove(ctx, data["header"]["uuid"])
        assert not folder.exists() and Path(removed["kept_at"]).is_dir()
        assert addons.list_packs(ctx) == []
    finally:
        await core.jobs.stop()
        core.db.close()


def test_the_add_on_routes_are_bedrock_only(multi_client):
    answer = multi_client.get("/api/servers/survival/addons")
    assert answer.status_code == 400 and "Mods page" in answer.json()["detail"]


# ====================================================================
# Mojang's EULA and Privacy Policy, and the download
# ====================================================================
def bedrock_zip(version: str = LATEST) -> bytes:
    return pack_zip(
        {
            # Big enough to pass the "is it a real program" size check.
            "bedrock_server": b"\x7fELF" + b"\0" * 4096,
            "bedrock_server.exe": b"MZ" + b"\0" * 4096,
            "server.properties": "server-name=Dedicated Server\nserver-port=19132\n"
            "server-portv6=19133\nlevel-name=Bedrock level\nmax-players=10\n",
            "allowlist.json": "[]",
            "permissions.json": "[]",
            "behavior_packs/vanilla/manifest.json": json.dumps(manifest("data")),
            "resource_packs/vanilla/manifest.json": json.dumps(manifest("resources")),
            f"release-notes-{version}.txt": "notes",
        }
    )


@pytest.fixture
def mojang(monkeypatch):
    """Mojang's links service and the zip, recording every request."""
    seen: list[str] = []
    state = {"version": LATEST, "zip": bedrock_zip()}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "net-secondary.web.minecraft-services.net":
            if state.get("down"):
                return httpx.Response(503)
            url = (
                "https://www.minecraft.net/bedrockdedicatedserver/bin-"
                f"{'win' if bedrock.DOWNLOAD_TYPE.endswith('Windows') else 'linux'}/"
                f"bedrock-server-{state['version']}.zip"
            )
            return httpx.Response(
                200,
                json={
                    "result": {
                        "links": [
                            {"downloadType": "serverJar", "downloadUrl": "https://example.com/x"},
                            {"downloadType": bedrock.DOWNLOAD_TYPE, "downloadUrl": url},
                        ]
                    }
                },
            )
        if request.url.path.endswith(".zip"):
            return httpx.Response(200, content=state["zip"])
        return httpx.Response(404)

    monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(handler))
    return seen, state


def test_only_mojangs_bedrock_paths_are_allowed():
    downloads.check_url(ZIP_URL)
    downloads.check_url(bedrock.LINKS_URL)
    for url in (
        "https://www.minecraft.net/en-us/download",
        "https://net-secondary.web.minecraft-services.net/api/v1.0/other",
        "http://www.minecraft.net/bedrockdedicatedserver/bin-win/x.zip",
    ):
        with pytest.raises(downloads.DownloadError):
            downloads.check_url(url)


async def test_nothing_is_downloaded_before_the_terms_are_accepted(tmp_path, mojang):
    seen, _ = mojang
    config = build_multi_config(tmp_path)
    core = AgentCore(config)
    try:
        with pytest.raises(InstallError, match="EULA and Privacy Policy"):
            await create_server(
                core,
                name="Bedrock",
                directory=str(tmp_path / "new-bedrock"),
                type_id="bedrock",
                minecraft=LATEST,
                eula_accepted=False,
            )
        assert seen == [], "not even the version list is fetched before the tick"
        assert not (tmp_path / "new-bedrock").exists()
        assert bedrock.terms(core.db) is None
        # And installing directly refuses too, before any request.
        plan = versions_module.Plan(
            type_id="bedrock", minecraft=LATEST, loader=None, downloads=[], jar=""
        )
        with pytest.raises(bedrock.BedrockError, match="have to be accepted"):
            await bedrock.install(core.servers["survival"], plan, tmp_path / "x")
        assert seen == []
    finally:
        await core.jobs.stop()
        core.db.close()


async def test_a_bedrock_server_is_created_and_its_download_kept(tmp_path, mojang):
    seen, state = mojang
    core = AgentCore(build_multi_config(tmp_path))
    try:
        result = await create_server(
            core,
            name="Phones",
            directory=str(tmp_path / "phones"),
            type_id="bedrock",
            minecraft=LATEST,
            eula_accepted=True,
            user="admin",
        )
        terms = bedrock.terms(core.db)
        assert terms and terms["user"] == "admin"
        assert result["verified"] is False, "Mojang publishes no checksum"
        assert result["sha256"] == hashlib.sha256(state["zip"]).hexdigest()
        folder = tmp_path / "phones"
        values = properties.PropertiesFile.read(folder / "server.properties").values()
        assert values["server-name"] == "Phones"
        assert (values["server-port"], values["server-portv6"]) == ("19132", "19133")
        assert not (folder / "eula.txt").exists()
        ctx = core.get_server(result["server_id"])
        assert ctx.config.server.jvm_args == []
        assert ctx.config.server.max_players == 10  # Mojang's default, from the file
        log_text = Path(result["install_log"]).read_text()
        assert f"SHA-256 {result['sha256']}" in log_text and "unverified" in log_text
        kept = bedrock.kept_versions()
        assert [k["version"] for k in kept] == [LATEST]
        assert ZIP_URL.rsplit("/", 1)[-1] in " ".join(seen)
    finally:
        await core.jobs.stop()
        core.db.close()


async def test_only_the_newest_or_a_kept_version_is_offered(tmp_path, mojang):
    seen, state = mojang
    core = AgentCore(build_multi_config(tmp_path))
    try:
        listed, problem = await bedrock.versions()
        assert [v.minecraft for v in listed] == [LATEST] and problem is None
        with pytest.raises(versions_module.VersionError, match="only offers the newest"):
            await bedrock.plan("1.21.80.3")
        # Once a version has been downloaded it stays installable after
        # Mojang moves on.
        plan = await bedrock.plan(LATEST)
        await bedrock.fetch(plan)
        state["version"] = "1.21.100.6"
        listed, _ = await bedrock.versions()
        assert {v.minecraft: v.kept for v in listed} == {"1.21.100.6": False, LATEST: True}
        kept_plan = await bedrock.plan(LATEST)
        assert kept_plan.downloads == [] and kept_plan.archive
        # Mojang unreachable: the kept ones are still offered, with a plain
        # sentence for the page (the error itself goes to the log).
        state["down"] = True
        listed, problem = await bedrock.versions()
        assert [v.minecraft for v in listed] == [LATEST]
        assert problem and problem.startswith("Mojang's version list couldn't be read")
        assert "503" not in problem
    finally:
        await core.jobs.stop()
        core.db.close()


async def test_a_kept_copy_that_changed_isnt_used(tmp_path, mojang):
    core = AgentCore(build_multi_config(tmp_path))
    try:
        plan = await bedrock.plan(LATEST)
        await bedrock.fetch(plan)
        Path(plan.archive).write_bytes(b"tampered")
        with pytest.raises(bedrock.BedrockError, match="has changed"):
            await bedrock.fetch(await bedrock.plan(LATEST))
    finally:
        await core.jobs.stop()
        core.db.close()


def test_a_download_with_a_zip_slip_path_is_refused(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(pack_zip({"bedrock_server.exe": b"MZ", "../evil.dll": b"x"}))
    with pytest.raises(bedrock.BedrockError, match="wasn't used"):
        bedrock.members(archive)


def test_an_update_keeps_the_worlds_settings_and_added_packs(tmp_path):
    folder = tmp_path / "srv"
    archive = tmp_path / "bds.zip"
    archive.write_bytes(bedrock_zip())
    infos = bedrock.members(archive)
    bedrock.unpack(archive, folder, infos)
    (folder / "server.properties").write_text("server-name=Mine\n")
    (folder / "worlds" / "w").mkdir(parents=True)
    (folder / "behavior_packs" / "MyPack_12345678").mkdir(parents=True)
    keep = tmp_path / "previous"
    moved = bedrock.move_aside(folder, keep, bedrock.shipped(infos))
    assert "bedrock_server.exe" in moved and "behavior_packs/vanilla" in moved
    assert "server.properties" not in moved
    bedrock.unpack(archive, folder, infos)
    assert (folder / "server.properties").read_text() == "server-name=Mine\n"
    assert (folder / "worlds" / "w").is_dir()
    assert (folder / "behavior_packs" / "MyPack_12345678").is_dir()
    assert (keep / "behavior_packs" / "vanilla" / "manifest.json").is_file()


# ====================================================================
# ports: UDP, and never Geyser's
# ====================================================================
async def test_a_new_bedrock_server_avoids_geysers_port(tmp_path):
    config = build_multi_config(tmp_path, servers=[("survival", "Survival", 25565)])
    config.for_server("survival").set("server.crossplay", True)
    config.for_server("survival").set("server.bedrock_port", 19132)
    core = AgentCore(config)
    try:
        pair = core.ports.suggest_bedrock_server()
        assert pair is not None and 19132 not in pair
        assert pair == (19134, 19135)
        offered = await options(core)
        assert offered["bedrock"]["port"] == 19134
    finally:
        await core.jobs.stop()
        core.db.close()


async def test_a_bedrock_server_and_geyser_on_one_port_cant_both_run(tmp_path):
    config = build_bedrock_config(tmp_path, java=True)
    config.for_server("java").set("server.crossplay", True)
    # the Bedrock server's IPv6 port
    config.for_server("java").set("server.bedrock_port", 19133)
    core = AgentCore(config)
    try:
        bedrock_ctx, java_ctx = core.servers["bedrock"], core.servers["java"]
        claimed = {(p.protocol, p.port) for p in core.ports.claimed(bedrock_ctx)}
        assert claimed == {("udp", 19132), ("udp", 19133)}
        assert ("udp", 19133) in {(p.protocol, p.port) for p in core.ports.claimed(java_ctx)}
        taken = core.ports.used(exclude="bedrock")
        assert taken[("udp", 19133)] == "java"
    finally:
        await core.jobs.stop()
        core.db.close()


# ====================================================================
# reachability: RakNet's unconnected ping
# ====================================================================
def pong(status: str) -> bytes:
    body = status.encode()
    return (
        bytes([raknet.UNCONNECTED_PONG])
        + struct.pack(">QQ", 1, 2)
        + raknet.MAGIC
        + struct.pack(">H", len(body))
        + body
    )


def test_a_pong_is_read_as_sent():
    found = raknet.parse_pong(pong("MCPE;My Server;800;1.21.95;2;10;123;Bedrock level;Survival"))
    assert found["name"] == "My Server" and found["version"] == "1.21.95"
    assert (found["players"], found["max_players"]) == (2, 10)


def test_anything_else_isnt_a_pong():
    assert raknet.parse_pong(b"") is None
    assert raknet.parse_pong(b"\x1c" + b"\x00" * 40) is None  # no magic
    ping = raknet.ping_packet(7)
    assert ping[0] == raknet.UNCONNECTED_PING and ping[9:25] == raknet.MAGIC


async def test_the_ping_reaches_a_local_udp_listener():
    loop = asyncio.get_running_loop()

    class Answer(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            if data[0] == raknet.UNCONNECTED_PING:
                self.transport.sendto(pong("MCPE;Local;800;1.21.95;0;10"), addr)

    transport, _ = await loop.create_datagram_endpoint(Answer, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    try:
        found = await asyncio.to_thread(raknet.ping, "127.0.0.1", port, 2.0)
        assert found and found["name"] == "Local"
    finally:
        transport.close()


# ====================================================================
# the pages: Java-only controls say "not applicable"
# ====================================================================
@pytest.fixture
def bedrock_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    with TestClient(create_app(build_bedrock_config(tmp_path, java=True))) as client:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


def test_the_server_list_says_what_bedrock_cant_do(bedrock_client):
    rows = {r["id"]: r for r in bedrock_client.get("/api/servers").json()["servers"]}
    assert rows["bedrock"]["edition"] == "bedrock"
    caps = rows["bedrock"]["capabilities"]
    assert caps == {
        "memory_limit": False,
        "speed": False,
        "crossplay": False,
        "reads_chat": False,
        "bans": False,
        "addons": True,
        "mods": False,
    }
    assert rows["java"]["capabilities"]["memory_limit"] is True
    assert rows["bedrock"]["game_port"]["protocol"] == "udp"


def test_crossplay_says_why_it_doesnt_apply(bedrock_client):
    body = bedrock_client.get("/api/servers/bedrock/crossplay").json()
    assert (
        body["available"] is False
        and "Bedrock players join it directly" in (body["unavailable_reason"])
    )


def test_how_friends_join_shows_only_the_bedrock_address(bedrock_client):
    body = bedrock_client.get("/api/servers/bedrock/join").json()
    assert body["java"] is None
    assert body["bedrock"]["port"] == 19132 and body["bedrock"]["protocol"] == "udp"
    assert body["bedrock"]["consoles_note"] is True


def test_game_settings_use_bedrocks_own_keys(bedrock_client):
    body = bedrock_client.get("/api/servers/bedrock/game-settings").json()
    keys = {f["key"] for f in body["fields"]}
    assert {"allow-list", "server-name", "allow-cheats"} <= keys
    assert "motd" not in keys and "pvp" not in keys
    answer = bedrock_client.put(
        "/api/servers/bedrock/game-settings", json={"values": {"motd": "hi"}}
    )
    assert answer.status_code == 400


def test_a_change_to_a_java_type_is_refused(bedrock_client):
    answer = bedrock_client.post(
        "/api/servers/bedrock/version/preflight",
        json={"type": "paper", "minecraft_version": "1.21.1"},
    )
    assert answer.status_code == 400 and "Create a new server instead" in answer.json()["detail"]


def test_the_terms_route_records_only_a_tick(bedrock_client):
    assert bedrock_client.get("/api/bedrock/terms").json()["accepted"] is False
    assert bedrock_client.post("/api/bedrock/terms", json={"accepted": False}).status_code == 400
    body = bedrock_client.post("/api/bedrock/terms", json={"accepted": True}).json()
    assert body["accepted"] is True and body["user"] == "admin"


def test_the_ban_list_is_marked_not_applicable(bedrock_client):
    body = bedrock_client.get("/api/servers/bedrock/players").json()
    assert body["bans"] is False and body["edition"] == "bedrock"
    assert body["lists"]["banned"]["not_applicable"] is True


# ====================================================================
# importing a .mcworld
# ====================================================================
def mcworld(name: str, version: list[int]) -> bytes:
    return pack_zip(
        {
            "level.dat": nbt.bedrock_level_for_tests(name, version),
            "levelname.txt": name,
            "db/CURRENT": "MANIFEST-000001\n",
            "db/000001.ldb": b"x" * 100,
        }
    )


def test_a_mcworld_is_read_as_a_bedrock_world(tmp_path):
    path = tmp_path / "w.mcworld"
    path.write_bytes(mcworld("Island", [1, 21, 100, 6, 0]))
    info, root = worldimport.inspect_zip(path)
    assert info.edition == "bedrock" and info.name == "Island"
    assert info.version == "1.21.100.6" and root == ""


def test_a_newer_world_is_flagged():
    assert worldimport.newer_than("1.21.100.6", "1.21.95.1") is True
    assert worldimport.newer_than("1.21.90", "1.21.95.1") is False
    assert worldimport.newer_than("1.21.90", None) is None


async def test_a_mcworld_goes_into_worlds_and_becomes_the_level(tmp_path):
    core = AgentCore(build_bedrock_config(tmp_path, java=True))
    try:
        ctx = core.servers["bedrock"]
        token, path = worldimport.new_upload(core)
        path.write_bytes(mcworld("Island: Two", [1, 21, 90, 0, 0]))
        result = await worldimport.import_world(ctx, token, user="admin")
        assert result["world"]["edition"] == "bedrock"
        folder = ctx.config.server_dir / "worlds" / "Island Two"
        assert (folder / "level.dat").is_file() and (folder / "db" / "000001.ldb").is_file()
        values = properties.PropertiesFile.read(ctx.config.server_dir / "server.properties")
        assert values.get("level-name") == "Island Two"
        assert (ctx.config.server_dir / "worlds" / "Bedrock level" / "level.dat").is_file()

        # A Bedrock world can't go into a Java server.
        token, path = worldimport.new_upload(core)
        path.write_bytes(mcworld("Other", [1, 21, 90, 0, 0]))
        with pytest.raises(worldimport.WorldImportError, match="Bedrock world"):
            await worldimport.import_world(core.servers["java"], token)
    finally:
        await core.jobs.stop()
        core.db.close()


def test_the_fake_bedrock_server_is_a_real_file():
    assert FAKE_BEDROCK.is_file()


async def test_an_update_and_its_roll_back_keep_the_servers_own_files(tmp_path, mojang):
    _, state = mojang
    core = AgentCore(build_multi_config(tmp_path))
    try:
        created = await create_server(
            core,
            name="Phones",
            directory=str(tmp_path / "phones"),
            type_id="bedrock",
            minecraft=LATEST,
            eula_accepted=True,
        )
        ctx = core.get_server(created["server_id"])
        folder = tmp_path / "phones"
        (folder / "worlds" / "Bedrock level").mkdir(parents=True)
        (folder / "worlds" / "Bedrock level" / "level.dat").write_bytes(b"world")
        (folder / "allowlist.json").write_text('[{"name": "Alex"}]')
        (folder / "behavior_packs" / "Mine_12345678").mkdir(parents=True)
        before = (folder / "server.properties").read_text()
        old_notes = folder / f"release-notes-{LATEST}.txt"
        assert old_notes.is_file()

        newer = "1.21.100.6"
        state["version"] = newer
        state["zip"] = bedrock_zip(newer)
        result = await install_module.change_version(ctx, "bedrock", newer, None, user="admin")
        assert result["verified"] is False
        assert (folder / f"release-notes-{newer}.txt").is_file()
        assert not old_notes.exists(), "the old program files were moved aside"
        assert (folder / "server.properties").read_text() == before
        assert (folder / "allowlist.json").read_text() == '[{"name": "Alex"}]'
        assert (folder / "worlds" / "Bedrock level" / "level.dat").read_bytes() == b"world"
        assert (folder / "behavior_packs" / "Mine_12345678").is_dir()
        assert ctx.server.pending_version["minecraft_version"] == newer

        await install_module.roll_back(ctx, user="admin")
        assert old_notes.is_file()
        assert not (folder / f"release-notes-{newer}.txt").exists()
        assert (folder / "server.properties").read_text() == before
        assert (folder / "behavior_packs" / "Mine_12345678").is_dir()
        # Both versions stay kept, so going forward again needs no download.
        assert {k["version"] for k in bedrock.kept_versions()} == {LATEST, newer}
    finally:
        await core.jobs.stop()
        core.db.close()


# ====================================================================
# Phase 8 review fixes
# ====================================================================
def test_a_world_name_with_a_comma_is_read_from_the_file_list():
    found = hold.parse_files("Mark, Sam/db/000005.ldb:1234, Mark, Sam/level.dat:2386")
    assert found == [("Mark, Sam/db/000005.ldb", 1234), ("Mark, Sam/level.dat", 2386)]
    with pytest.raises(hold.HoldError):
        hold.parse_files("Bedrock level/level.dat:12 and more")


def test_world_files_the_list_leaves_out_are_copied_whole(tmp_path):
    """save query may list only the database and level.dat. The files beside
    them (which add-ons the world has on) still go into the copy."""
    worlds = tmp_path / "worlds"
    world = worlds / "Bedrock level"
    (world / "db").mkdir(parents=True)
    (world / "db" / "000005.ldb").write_bytes(b"db")
    (world / "db" / "LOG").write_bytes(b"log")
    (world / "level.dat").write_bytes(b"level")
    (world / "world_behavior_packs.json").write_text('[{"pack_id": "x"}]')
    (worlds / "Other world").mkdir()
    (worlds / "Other world" / "level.dat").write_bytes(b"other")
    staging = tmp_path / "staging"
    listed = ["Bedrock level/db/000005.ldb", "Bedrock level/level.dat"]
    extra = hold.copy_unlisted(worlds, staging, listed)
    assert extra == ["Bedrock level/world_behavior_packs.json"]
    assert (staging / "Bedrock level" / "world_behavior_packs.json").read_text() == (
        '[{"pack_id": "x"}]'
    )
    # The database is only ever copied as listed, and other worlds not at all.
    assert not (staging / "Bedrock level" / "db" / "LOG").exists()
    assert not (staging / "Other world").exists()


def test_the_packs_inside_a_world_template_are_found():
    template = pack_zip(
        {
            "manifest.json": json.dumps(manifest("world_template")),
            "level.dat": b"level",
            "behavior_packs/bp/manifest.json": json.dumps(manifest("data", name="BP")),
            "resource_packs/rp/manifest.json": json.dumps(manifest("resources", name="RP")),
        }
    )
    found = addons.read_upload("Castle.mctemplate", template)
    assert sorted((f.manifest["kind"], f.prefix) for f in found) == [
        ("behavior", "behavior_packs/bp/"),
        ("resource", "resource_packs/rp/"),
    ]


def test_an_update_keeps_the_development_pack_folders(tmp_path):
    folder = tmp_path / "srv"
    archive = tmp_path / "bds.zip"
    with zipfile.ZipFile(io.BytesIO(bedrock_zip())) as zf:
        files = {name: zf.read(name) for name in zf.namelist()}
    files["development_behavior_packs/"] = b""
    archive.write_bytes(pack_zip(files))
    infos = bedrock.members(archive)
    bedrock.unpack(archive, folder, infos)
    mine = folder / "development_behavior_packs" / "Mine"
    mine.mkdir(parents=True)
    assert "development_behavior_packs" not in bedrock.shipped(infos)["top"]
    bedrock.move_aside(folder, tmp_path / "previous", bedrock.shipped(infos))
    bedrock.unpack(archive, folder, infos)
    assert mine.is_dir()


def test_the_game_port_cant_be_the_servers_own_ipv6_port(bedrock_client):
    answer = bedrock_client.put(
        "/api/servers/bedrock/game-settings", json={"values": {"server-port": 19133}}
    )
    assert answer.status_code == 400
    assert "IPv6" in json.dumps(answer.json())
