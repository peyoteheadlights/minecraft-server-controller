"""Server types, version lists, version and type changes, and crossplay.

Every official source (Mojang, Fabric, Quilt, Forge, NeoForge, Paper,
Purpur, GeyserMC) is replaced by a fake network, so the real code paths
run - the safe downloader's host allow-list and checksum checks, the
installer runner, the safe-change routine and the job tracker - without a
single real request. Where only a running server can prove something (each
type's version line, and the version staying pending until the console
reports it), the fake Minecraft server prints the real line.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import httpx
import pytest

from agent import crossplay, downloads, servertypes
from agent.core import AgentCore
from agent.minecraft.console import extract_signals, parse_line
from agent.servertypes import create as create_module
from agent.servertypes import install as install_module
from agent.servertypes import versions as versions_module

from .conftest import build_multi_config
from .test_mods import make_jar

MC = "1.21.1"
SERVER_JAR = b"PK\x03\x04" + b"a pretend server jar" * 80
INSTALLER_JAR = b"PK\x03\x04" + b"a pretend installer" * 80


# ---------------------------------------------------------------- fake network
def _json(data) -> httpx.Response:
    return httpx.Response(200, json=data)


def fake_sources(
    *,
    paper_sha: str | None = None,
    purpur_md5: str | None = None,
    geyser_sha: str | None = None,
    vanilla_sha1: str | None = None,
):
    """One handler standing in for every official version source."""
    paper_sha = paper_sha if paper_sha is not None else hashlib.sha256(SERVER_JAR).hexdigest()
    purpur_md5 = purpur_md5 if purpur_md5 is not None else hashlib.md5(SERVER_JAR).hexdigest()
    geyser_sha = geyser_sha if geyser_sha is not None else hashlib.sha256(SERVER_JAR).hexdigest()
    vanilla_sha1 = (
        vanilla_sha1 if vanilla_sha1 is not None else hashlib.sha1(SERVER_JAR).hexdigest()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host, path = request.url.host, request.url.path
        if host == "piston-meta.mojang.com" and path.endswith("version_manifest_v2.json"):
            return _json(
                {
                    "latest": {"release": MC, "snapshot": "24w40a"},
                    "versions": [
                        {
                            "id": "24w40a",
                            "type": "snapshot",
                            "url": "https://piston-meta.mojang.com/v1/24w40a.json",
                            "releaseTime": "2024-10-02T00:00:00+00:00",
                        },
                        {
                            "id": MC,
                            "type": "release",
                            "url": f"https://piston-meta.mojang.com/v1/{MC}.json",
                            "releaseTime": "2024-08-08T00:00:00+00:00",
                        },
                        {
                            "id": "1.7.10",
                            "type": "release",
                            "url": "https://piston-meta.mojang.com/v1/1.7.10.json",
                            "releaseTime": "2014-05-14T00:00:00+00:00",
                        },
                    ],
                }
            )
        if host == "piston-meta.mojang.com" and path.endswith("1.7.10.json"):
            return _json({"downloads": {}})  # no server download published
        if host == "piston-meta.mojang.com":
            return _json(
                {
                    "downloads": {
                        "server": {
                            "url": "https://piston-data.mojang.com/v1/server.jar",
                            "sha1": vanilla_sha1,
                            "size": len(SERVER_JAR),
                        }
                    }
                }
            )
        if host == "piston-data.mojang.com":
            return httpx.Response(200, content=SERVER_JAR)
        if host == "meta.fabricmc.net":
            if path.endswith("/versions/game"):
                return _json(
                    [
                        {"version": MC, "stable": True},
                        {"version": "1.20.1", "stable": True},
                        {"version": "24w40a", "stable": False},
                    ]
                )
            if path.endswith("/versions/loader"):
                return _json(
                    [{"version": "0.16.5", "stable": True}, {"version": "0.16.6", "stable": False}]
                )
            if path.endswith("/versions/installer"):
                return _json([{"version": "1.0.1", "stable": True}])
            if path.endswith("/0.16.5/1.0.1/server/jar"):
                return httpx.Response(200, content=SERVER_JAR)
            if path.endswith("/server/jar"):
                return httpx.Response(404)  # without the installer version
        if host == "meta.quiltmc.org":
            if path.endswith("/versions/game"):
                return _json([{"version": MC, "stable": True}])
            if path.endswith("/versions/loader"):
                return _json([{"version": "0.26.0", "stable": True}])
            if path.endswith("/versions/installer"):
                return _json(
                    [
                        {
                            "version": "0.9.2",
                            "url": "https://maven.quiltmc.org/repository/release/"
                            "org/quiltmc/quilt-installer/0.9.2/quilt-installer-0.9.2.jar",
                        }
                    ]
                )
        if host == "maven.quiltmc.org":
            return httpx.Response(200, content=INSTALLER_JAR)
        if host == "maven.minecraftforge.net":
            if path.endswith("maven-metadata.xml"):
                return httpx.Response(
                    200,
                    text=(
                        "<metadata><versioning><versions>"
                        "<version>1.20.1-47.2.0</version>"
                        f"<version>{MC}-52.0.40</version>"
                        "</versions></versioning></metadata>"
                    ),
                )
            if path.endswith(".sha1"):
                return httpx.Response(200, text=hashlib.sha1(INSTALLER_JAR).hexdigest())
            return httpx.Response(200, content=INSTALLER_JAR)
        if host == "maven.neoforged.net":
            if path.endswith("maven-metadata.xml"):
                return httpx.Response(
                    200,
                    text=(
                        "<metadata><versioning><versions>"
                        "<version>21.1.9</version><version>20.4.100</version>"
                        "</versions></versioning></metadata>"
                    ),
                )
            if path.endswith(".sha1"):
                return httpx.Response(404, text="no checksum")
            return httpx.Response(200, content=INSTALLER_JAR)
        if host == "fill.papermc.io":
            if path.endswith("/builds"):
                return _json(
                    [
                        {
                            "id": 129,
                            "channel": "STABLE",
                            "downloads": {
                                "server:default": {
                                    "url": "https://fill-data.papermc.io/paper-129.jar",
                                    "checksums": {"sha256": paper_sha},
                                    "size": len(SERVER_JAR),
                                }
                            },
                        }
                    ]
                )
            return _json({"versions": {"1.21": [MC, "1.21"]}})
        if host == "fill-data.papermc.io":
            return httpx.Response(200, content=SERVER_JAR)
        if host == "api.purpurmc.org":
            if path.endswith("/download"):
                return httpx.Response(200, content=SERVER_JAR)
            if path.rstrip("/").endswith("purpur"):
                return _json({"versions": ["1.20.1", MC]})
            if path.count("/") >= 4:  # /v2/purpur/<mc>/<build>
                return _json({"md5": purpur_md5} if purpur_md5 else {})
            return _json({"builds": {"latest": "2301"}})
        if host == "download.geysermc.org":
            if "/downloads/" in path:
                return httpx.Response(200, content=SERVER_JAR)
            if path.endswith("/builds/latest"):
                project = "geyser" if "geyser" in path else "floodgate"
                return _json(
                    {
                        "version": "2.4.2",
                        "build": 700,
                        "downloads": {
                            "fabric": {"sha256": geyser_sha},
                            "spigot": {"sha256": geyser_sha},
                            "neoforge": {"sha256": geyser_sha},
                        },
                        "project": project,
                    }
                )
            return _json({"versions": ["2.4.2"]})
        raise AssertionError(f"unexpected request to {url}")

    return handler


@pytest.fixture
def network(monkeypatch):
    """Point the safe downloader at the fake sources."""

    def install(**kwargs):
        monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(fake_sources(**kwargs)))

    install()
    return install


@pytest.fixture
async def core(tmp_path, network):
    agent = AgentCore(build_multi_config(tmp_path))
    yield agent
    await agent.jobs.stop()
    agent.db.close()


@pytest.fixture
def ctx(core):
    return core.servers["survival"]


@pytest.fixture
def fake_installer(monkeypatch):
    """Stand in for the Forge/NeoForge/Quilt installer, recording exactly
    how it was launched (an argument list, no shell, in the server folder)."""
    calls: list[dict] = []
    real = asyncio.create_subprocess_exec

    async def fake(*args, **kwargs):
        if "--installServer" not in args and "install" not in args:
            return await real(*args, **kwargs)
        calls.append({"argv": list(args), **kwargs})
        folder = kwargs["cwd"]
        if "install" in args:
            # the Quilt installer leaves a launcher jar behind
            Path(folder, "quilt-server-launch.jar").write_bytes(SERVER_JAR)
        else:
            # Forge and NeoForge write an argument file for each system
            target = os.path.join(folder, "libraries", "net", "neoforged", "neoforge")
            os.makedirs(target, exist_ok=True)
            for name, separator in (("win_args.txt", ";"), ("unix_args.txt", ":")):
                Path(target, name).write_text(
                    f"-p libraries/a.jar{separator}libraries/b.jar net.minecraft.server.Main\n",
                    encoding="utf-8",
                )

        class Done:
            returncode = 0

            async def communicate(self):
                return b"Installing...\nThe server installed successfully\n", b""

        return Done()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    return calls


# ---------------------------------------------------------------- the types
def test_every_type_declares_what_it_supports():
    catalog = {entry["id"]: entry for entry in servertypes.catalog()}
    assert set(catalog) == {
        "vanilla",
        "fabric",
        "quilt",
        "forge",
        "neoforge",
        "paper",
        "purpur",
        "bedrock",
    }
    assert catalog["bedrock"]["edition"] == "bedrock"
    assert catalog["bedrock"]["game_protocol"] == "udp"
    assert catalog["vanilla"]["content"] is None, "vanilla takes no mods or plugins"
    assert catalog["paper"]["content"] == "plugins"
    assert catalog["fabric"]["content"] == "mods"
    # Exactly one row is marked "recommended for most people".
    assert [entry["id"] for entry in catalog.values() if entry["recommended"]] == ["fabric"]
    # Crossplay is a capability, not a guess: only the types GeyserMC
    # publishes a build for have it.
    assert {k for k, v in catalog.items() if v["crossplay"]} == {
        "fabric",
        "neoforge",
        "paper",
        "purpur",
    }


def test_an_unknown_type_is_refused_by_name():
    with pytest.raises(servertypes.UnknownServerType, match="fabrik"):
        servertypes.get("fabrik")


def test_an_existing_server_is_fabric_by_default(config):
    assert config.server.type == "fabric"
    assert config.server_type.id == "fabric"


@pytest.mark.parametrize(
    "raw,type_id,version,loader",
    [
        (
            "[10:00:00] [main/INFO]: Loading Minecraft 1.21.1 with Fabric Loader 0.16.5",
            "fabric",
            "1.21.1",
            "0.16.5",
        ),
        (
            "[10:00:00] [main/INFO]: Loading Minecraft 1.21.1 with Quilt Loader 0.26.0",
            "quilt",
            "1.21.1",
            "0.26.0",
        ),
        ("[10:00:00] [main/INFO]: MinecraftForge v47.3.0 Initialized", "forge", None, "47.3.0"),
        ("[10:00:00] [main/INFO]: NeoForge v21.1.9 Initialized", "neoforge", None, "21.1.9"),
        (
            "[10:00:00] [Server thread/INFO]: This server is running Paper version "
            "1.21.1-129-main@abc (MC: 1.21.1)",
            "paper",
            "1.21.1",
            "1.21.1-129-main@abc",
        ),
        (
            "[10:00:00] [Server thread/INFO]: This server is running Purpur version "
            "1.21.1-2301 (MC: 1.21.1)",
            "purpur",
            "1.21.1",
            "1.21.1-2301",
        ),
        (
            "[10:00:00] [main/INFO]: Forge mod loading, version 47.3.0, for MC 1.20.1 "
            "with MCP 20230612.114412",
            "forge",
            "1.20.1",
            "47.3.0",
        ),
        (
            # newer Paper prints no "(MC: ...)"; the version comes from
            # Minecraft's own "Starting minecraft server version" line
            "[10:00:00] [Server thread/INFO]: This server is running Paper version "
            "1.21.4-232-ver/1.21.4@12ff3e3 (2025-03-12T10:00:00Z) (Implementing API version "
            "1.21.4-R0.1-SNAPSHOT)",
            "paper",
            None,
            "1.21.4-232-ver/1.21.4@12ff3e3",
        ),
    ],
)
def test_each_types_version_line_is_detected(raw, type_id, version, loader):
    sig = extract_signals(parse_line(raw, 1))
    assert sig.mc_version == version
    assert sig.loader_version == loader
    assert servertypes.detected_type(sig.loader_name) == type_id


# ---------------------------------------------------------------- version lists
async def test_vanilla_versions_come_from_mojangs_list(network):
    found = await versions_module.list_versions("vanilla")
    assert [v.minecraft for v in found][:2] == ["24w40a", MC]
    snapshot = next(v for v in found if v.minecraft == "24w40a")
    assert snapshot.stable is False, "a snapshot is never offered as stable"
    assert versions_module.latest_stable(found).minecraft == MC


async def test_fabric_versions_and_loaders_come_from_fabric_meta(network):
    payload = versions_module.versions_payload(
        "fabric", await versions_module.list_versions("fabric")
    )
    assert payload["latest_stable"] == MC
    assert payload["picks_loader"] is True
    assert payload["source_host"] == "meta.fabricmc.net"
    assert "0.16.5" in payload["versions"][0]["loaders"]


async def test_forge_versions_are_grouped_by_minecraft_version(network):
    found = {v.minecraft: v for v in await versions_module.list_versions("forge")}
    assert found[MC].loaders == [f"{MC}-52.0.40"]
    assert found["1.20.1"].loaders == ["1.20.1-47.2.0"]


async def test_neoforge_versions_map_onto_their_minecraft_version(network):
    found = {v.minecraft: v for v in await versions_module.list_versions("neoforge")}
    assert found["1.21.1"].loaders == ["21.1.9"]
    assert found["1.20.4"].loaders == ["20.4.100"]


@pytest.mark.parametrize(
    "build, minecraft",
    [
        ("21.1.9", "1.21.1"),
        ("21.0.3-beta", "1.21"),
        ("26.1.0.5", "26.1"),  # year-based Minecraft versions
        ("26.1.1.2", "26.1.1"),
        ("0.25w14a.3-beta", "25w14a"),  # a snapshot build
    ],
)
def test_each_neoforge_build_names_the_right_minecraft_version(build, minecraft):
    assert versions_module._neoforge_minecraft(build) == minecraft


def test_versions_sort_by_number_not_by_the_order_a_source_sends():
    names = ["1.21", "1.21.10", "1.20.1", "1.21.2", "1.21-pre1"]
    assert sorted(names, key=versions_module.version_key, reverse=True) == [
        "1.21.10",
        "1.21.2",
        "1.21",
        "1.21-pre1",
        "1.20.1",
    ]


async def test_forge_older_than_1_17_is_not_offered(network, monkeypatch):
    """Forge only writes the argument file the app starts it from since
    Minecraft 1.17, so older Forge versions could never be launched."""

    async def xml(url, max_bytes=0):
        return (
            "<metadata><versioning><versions>"
            "<version>1.12.2-14.23.5.2860</version><version>1.20.1-47.2.0</version>"
            "<version>1.20.1-47.10.0</version>"
            "</versions></versioning></metadata>"
        )

    monkeypatch.setattr(downloads, "fetch_text", xml)
    found = {v.minecraft: v for v in await versions_module.list_versions("forge")}
    assert "1.12.2" not in found
    assert found["1.20.1"].loaders[0] == "1.20.1-47.10.0"  # newest build first, by number


async def test_the_fabric_launcher_address_names_the_installer_version(network):
    plan = await versions_module.make_plan("fabric", MC, "0.16.5")
    assert plan.downloads[0].spec.url.endswith(f"/{MC}/0.16.5/1.0.1/server/jar")


async def test_quilt_is_installed_with_its_own_install_command(ctx, network, fake_installer):
    plan = await versions_module.make_plan("quilt", MC, "0.26.0")
    result = await install_module.install_plan(ctx, plan, ctx.config.server_dir)
    call = fake_installer[0]
    assert call["argv"][1:] == [
        "-jar",
        "quilt-installer.jar",
        "install",
        "server",
        MC,
        "0.26.0",
        "--download-server",
        "--install-dir=.",
    ]
    assert call["cwd"] == str(ctx.config.server_dir)
    assert result["jar"] == "quilt-server-launch.jar"


async def test_paper_and_purpur_versions_come_from_their_apis(network):
    paper = await versions_module.list_versions("paper")
    assert MC in [v.minecraft for v in paper]
    purpur = await versions_module.list_versions("purpur")
    assert [v.minecraft for v in purpur][0] == MC  # newest first


async def test_a_version_the_source_does_not_offer_is_refused(network):
    with pytest.raises(versions_module.VersionError, match="doesn't offer|doesn't list"):
        await versions_module.make_plan("vanilla", "1.99.9")


async def test_a_version_with_no_server_download_is_explained(network):
    with pytest.raises(versions_module.VersionError, match="server download"):
        await versions_module.make_plan("vanilla", "1.7.10")


@pytest.mark.parametrize("value", ["../etc/passwd", "1.21.1 && calc", "", "a" * 80])
async def test_a_version_that_is_not_a_version_never_reaches_a_url(value):
    with pytest.raises(versions_module.VersionError):
        versions_module.check_version(value)


# ---------------------------------------------------------------- the downloader
@pytest.mark.parametrize(
    "url",
    [
        "http://piston-data.mojang.com/server.jar",  # not https
        "https://evil.example.com/server.jar",  # not an official host
        "https://piston-data.mojang.com:8443/server.jar",  # odd port
    ],
)
def test_the_downloader_refuses_anything_but_official_https(url):
    with pytest.raises(downloads.DownloadError):
        downloads.check_url(url)


async def test_a_checksum_mismatch_leaves_no_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloads,
        "TRANSPORT",
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"something else")),
    )
    spec = downloads.FileSpec(
        url="https://piston-data.mojang.com/v1/server.jar",
        name="server.jar",
        sha1=hashlib.sha1(SERVER_JAR).hexdigest(),
    )
    with pytest.raises(downloads.DownloadError, match="checksum"):
        await downloads.download(spec, tmp_path)
    assert list(tmp_path.iterdir()) == [], "a failed download leaves nothing, not even a part file"


async def test_a_source_with_no_checksum_is_recorded_as_unverified(tmp_path, network):
    plan = await versions_module.make_plan("fabric", MC, "0.16.5")
    assert plan.verified is False, "Fabric publishes no checksum for its launcher jar"
    fetched = await downloads.download(plan.downloads[0].spec, tmp_path)
    assert fetched.verified is False
    assert fetched.checked_with is None
    assert fetched.sha256 == hashlib.sha256(SERVER_JAR).hexdigest()


async def test_a_published_checksum_is_checked(tmp_path, network):
    plan = await versions_module.make_plan("vanilla", MC)
    fetched = await downloads.download(plan.downloads[0].spec, tmp_path)
    assert fetched.verified is True
    assert fetched.checked_with == "sha1"


async def test_paper_is_checked_against_its_published_sha256(tmp_path, network):
    plan = await versions_module.make_plan("paper", MC)
    fetched = await downloads.download(plan.downloads[0].spec, tmp_path)
    assert fetched.checked_with == "sha256"
    network(paper_sha="0" * 64)
    with pytest.raises(downloads.DownloadError, match="checksum"):
        plan = await versions_module.make_plan("paper", MC)
        await downloads.download(plan.downloads[0].spec, tmp_path / "again")


async def test_a_file_bigger_than_the_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloads,
        "TRANSPORT",
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 5000)),
    )
    spec = downloads.FileSpec(
        url="https://piston-data.mojang.com/v1/server.jar", name="server.jar", max_bytes=1000
    )
    with pytest.raises(downloads.DownloadError, match="bigger than"):
        await downloads.download(spec, tmp_path)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- installing
async def test_installing_vanilla_puts_a_launchable_jar_in_place(ctx, network):
    plan = await versions_module.make_plan("vanilla", MC)
    result = await install_module.install_plan(ctx, plan, ctx.config.server_dir)
    assert (ctx.config.server_dir / "server.jar").is_file()
    assert result["jar"] == "server.jar"
    assert result["verified"] is True
    assert result["unverified_note"] is None


async def test_an_unverified_download_says_so_rather_than_claiming_a_check(ctx, network):
    plan = await versions_module.make_plan("fabric", MC, "0.16.5")
    result = await install_module.install_plan(ctx, plan, ctx.config.server_dir)
    assert result["verified"] is False
    assert "no checksum" in result["unverified_note"]


async def test_neoforge_is_installed_by_running_its_installer_once(ctx, network, fake_installer):
    plan = await versions_module.make_plan("neoforge", "1.21.1", "21.1.9")
    result = await install_module.install_plan(ctx, plan, ctx.config.server_dir)
    # The installer ran as an argument list, never a shell, in the server folder.
    assert len(fake_installer) == 1
    call = fake_installer[0]
    assert call["argv"][1:] == ["-jar", "neoforge-installer.jar", "--installServer"]
    assert call["cwd"] == str(ctx.config.server_dir)
    assert call["stdin"] == asyncio.subprocess.DEVNULL
    # It leaves the argument file the server is launched from, and its own
    # output is kept as a log.
    # the argument file for this system: unix_args.txt separates paths
    # with ":", which Java on Windows can't read
    assert result["args_file"].endswith("win_args.txt" if os.name == "nt" else "unix_args.txt")
    assert result["jar"] == ""
    install_log = Path(result["install_log"]).read_text(encoding="utf-8")
    assert "installed successfully" in install_log
    # The downloaded installer itself is not left lying around.
    assert not (ctx.config.server_dir / "neoforge-installer.jar").exists()


async def test_a_forge_install_that_leaves_no_start_file_is_reported(ctx, network, monkeypatch):
    async def fake(*args, **kwargs):
        class Done:
            returncode = 0

            async def communicate(self):
                return b"nothing was written\n", b""

        return Done()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    plan = await versions_module.make_plan("forge", MC, f"{MC}-52.0.40")
    with pytest.raises(install_module.InstallError, match="start file"):
        await install_module.install_plan(ctx, plan, ctx.config.server_dir)


async def test_a_failed_installer_keeps_its_log_and_changes_nothing(ctx, network, monkeypatch):
    async def fake(*args, **kwargs):
        class Failed:
            returncode = 1

            async def communicate(self):
                return b"Exception: could not download libraries\n", b""

        return Failed()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    plan = await versions_module.make_plan("forge", MC, f"{MC}-52.0.40")
    with pytest.raises(install_module.InstallError, match="failed"):
        await install_module.install_plan(ctx, plan, ctx.config.server_dir)
    logs = list((ctx.config.data_dir / install_module.INSTALL_LOG).glob("*.log"))
    assert logs and "could not download libraries" in logs[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------- the preflight
async def test_the_preflight_says_what_will_happen_in_plain_words(ctx, network):
    make_jar(ctx.config.mods_dir / "sodium.jar", "sodium", "0.5.8", depends={"minecraft": ">=1.21"})
    make_jar(ctx.config.mods_dir / "oldmod.jar", "oldmod", "1.0", depends={"minecraft": "1.19.x"})
    ctx.server.mc_version = "1.20.1"
    report = await install_module.preflight(ctx, "fabric", MC, "0.16.5")
    assert report["current"]["minecraft_version"] == "1.20.1"
    assert report["target"]["minecraft_version"] == MC
    assert report["direction"] == "newer"
    assert report["downgrade_warning"] is False
    declared = {item["filename"]: item["declares_target"] for item in report["content"]}
    assert declared["sodium.jar"] is True
    assert declared["oldmod.jar"] is False
    assert report["type_change"] is False


async def test_a_downgrade_is_warned_about(ctx, network):
    ctx.server.mc_version = MC
    report = await install_module.preflight(ctx, "fabric", "1.20.1", "0.16.5")
    assert report["direction"] == "older"
    assert report["downgrade_warning"] is True


async def test_an_unobserved_version_is_unknown_in_the_preflight(ctx, network):
    ctx.server.mc_version = None
    report = await install_module.preflight(ctx, "fabric", MC, "0.16.5")
    assert report["current"]["minecraft_version"] is None
    assert report["current"]["observed"] is False
    assert report["direction"] == "same" or report["direction"] == "same"


async def test_a_mod_that_declares_nothing_is_unknown_not_assumed(ctx, network):
    make_jar(ctx.config.mods_dir / "quiet.jar", "quiet", "1.0")
    report = await install_module.preflight(ctx, "fabric", MC, "0.16.5")
    item = next(i for i in report["content"] if i["filename"] == "quiet.jar")
    assert item["declares_target"] is None
    assert "quiet.jar" in report["unknown_support"]


async def test_a_type_change_lists_the_mods_that_would_be_moved_aside(ctx, network):
    make_jar(ctx.config.mods_dir / "sodium.jar", "sodium", "0.5.8")
    report = await install_module.preflight(ctx, "paper", MC)
    assert report["type_change"] is True
    assert report["moved_aside"] == ["sodium.jar"]
    assert report["target_content_kind"] == "plugins"


async def test_vanilla_to_paper_is_marked_the_gentle_case(ctx, network):
    ctx.config.set("server.type", "vanilla")
    report = await install_module.preflight(ctx, "paper", MC)
    assert report["gentle_type_change"] is True


# ---------------------------------------------------------------- changing version
async def test_a_version_change_backs_up_first_and_stays_pending(ctx, network):
    events = []
    ctx.bus.subscribe(lambda event: events.append(event))
    ctx.server.mc_version = "1.20.1"
    (ctx.config.server_dir / "server.jar").write_bytes(b"old jar")
    result = await install_module.change_version(ctx, "vanilla", MC, user="tester")

    # A verified backup was taken before anything changed, and is the undo.
    assert result["safety_backup"]["verified"] is True
    assert result["undo"]["backup_id"] == result["safety_backup"]["id"]
    assert result["undo"]["kind"] == "restore_backup"
    backups = ctx.backups.list_backups()
    assert backups and backups[-1]["kind"] == "safety"
    assert backups[-1]["created_at"] <= os.path.getmtime(ctx.config.server_dir / "server.jar")
    # The new software is in place and the config follows it.
    assert ctx.config.server.type == "vanilla"
    assert ctx.config.server.jar == "server.jar"
    # The version is pending until the console says otherwise (house rule 1).
    assert result["pending"] is True
    assert ctx.server.mc_version is None
    assert ctx.server.status()["pending_version"]["minecraft_version"] == MC
    assert ctx.server.status()["minecraft_version"] is None
    assert any(e.type == "version_changed" for e in events)


async def test_the_version_is_only_confirmed_once_the_console_reports_it(ctx, network, monkeypatch):
    monkeypatch.setenv("FAKE_MC_VERSION", MC)
    monkeypatch.setenv("FAKE_TYPE", "vanilla")
    ctx.server.pending_version = {"type": "vanilla", "minecraft_version": MC}
    events = []
    ctx.bus.subscribe(lambda event: events.append(event.type))
    await ctx.server.start()
    assert await ctx.server.wait_online(timeout=20)
    try:
        assert ctx.server.mc_version == MC, "the version comes from the console, nowhere else"
        assert ctx.server.pending_version is None
        assert "version_confirmed" in events
    finally:
        await ctx.server.stop()


async def test_a_failed_download_leaves_the_old_files_in_place(ctx, monkeypatch, network):
    jar = ctx.config.server_dir / "server.jar"
    jar.write_bytes(b"the old server jar")
    network(vanilla_sha1="0" * 40)  # the download will not match its checksum
    with pytest.raises(Exception, match="checksum|didn't match"):
        await install_module.change_version(ctx, "vanilla", MC, user="tester")
    assert jar.read_bytes() == b"the old server jar", "the old jar must still be there"
    assert ctx.config.server.type == "fabric", "the type only changes once the change worked"


async def test_a_type_change_moves_incompatible_mods_aside_rather_than_deleting(ctx, network):
    make_jar(ctx.config.mods_dir / "sodium.jar", "sodium", "0.5.8")
    await install_module.change_version(ctx, "paper", MC, user="tester")
    assert not (ctx.config.server_dir / "mods" / "sodium.jar").exists()
    moved = list(ctx.config.mod_trash_dir.rglob("sodium.jar"))
    assert moved, "the mod is kept, not deleted"
    assert ctx.config.server_type.content == "plugins"
    assert ctx.config.mods_dir.name == "plugins"


async def test_a_change_can_be_rolled_back_in_one_step(ctx, network):
    (ctx.config.server_dir / "fabric-server-launch.jar").write_bytes(b"the fabric launcher")
    make_jar(ctx.config.mods_dir / "sodium.jar", "sodium", "0.5.8")
    await install_module.change_version(ctx, "paper", MC, user="tester")
    assert (ctx.config.server_dir / "paper.jar").is_file()

    result = await install_module.roll_back(ctx, user="tester")
    assert "fabric-server-launch.jar" in result["restored"]
    assert ctx.config.server.type == "fabric"
    assert (
        ctx.config.server_dir / "fabric-server-launch.jar"
    ).read_bytes() == b"the fabric launcher"
    assert (ctx.config.mods_dir / "sodium.jar").is_file(), "the mods come back too"


async def test_rolling_back_with_nothing_to_go_back_to_is_refused(ctx):
    with pytest.raises(install_module.InstallError, match="no previous version"):
        await install_module.roll_back(ctx)


# ---------------------------------------------------------------- new servers
async def test_a_new_server_is_not_created_without_the_eula_being_accepted(core, tmp_path):
    with pytest.raises(install_module.InstallError, match="EULA"):
        await create_module.create_server(
            core,
            name="Fresh",
            directory=str(tmp_path / "fresh"),
            type_id="vanilla",
            minecraft=MC,
            eula_accepted=False,
        )
    assert not (tmp_path / "fresh").exists(), "nothing is created until the rules are accepted"


async def test_a_new_server_is_set_up_and_registered(core, tmp_path, network, monkeypatch):
    # Whatever Java this machine has is beside the point here (the CI runner
    # has 17, Minecraft 1.21 needs 21): the Java check has its own test below.
    monkeypatch.setattr(create_module, "java_problem", lambda *args, **kwargs: None)
    folder = tmp_path / "fresh"
    result = await create_module.create_server(
        core,
        name="Fresh World",
        directory=str(folder),
        type_id="vanilla",
        minecraft=MC,
        eula_accepted=True,
        user="tester",
    )
    assert (folder / "server.jar").is_file()
    properties = (folder / "server.properties").read_text(encoding="utf-8")
    assert f"server-port={result['port']}" in properties
    assert "motd=Fresh World" in properties
    # eula=true only because the person accepted it.
    assert "eula=true" in (folder / "eula.txt").read_text(encoding="utf-8")
    assert result["server_id"] in core.servers
    # Nothing was started, and the version is not claimed yet.
    new_ctx = core.get_server(result["server_id"])
    assert new_ctx.server.running is False
    assert new_ctx.server.status()["minecraft_version"] is None
    assert new_ctx.server.status()["pending_version"]["minecraft_version"] == MC


async def test_a_new_servers_eula_file_says_false_until_it_is_accepted(tmp_path):
    create_module.write_eula(tmp_path, False)
    assert "eula=false" in (tmp_path / "eula.txt").read_text(encoding="utf-8")
    create_module.write_eula(tmp_path, True)
    assert "eula=true" in (tmp_path / "eula.txt").read_text(encoding="utf-8")


async def test_a_folder_that_already_has_files_is_refused(core, tmp_path, network):
    folder = tmp_path / "taken"
    folder.mkdir()
    (folder / "world").mkdir()
    with pytest.raises(Exception, match="already has files"):
        await create_module.create_server(
            core,
            name="Taken",
            directory=str(folder),
            type_id="vanilla",
            minecraft=MC,
            eula_accepted=True,
        )


async def test_java_too_old_is_said_before_anything_is_downloaded(
    core, tmp_path, network, monkeypatch
):
    from agent.minecraft import java as java_module

    monkeypatch.setattr(
        create_module,
        "java_problem",
        lambda *a, **k: {
            "problem": "Minecraft 1.21.1 needs Java 21 or newer, but this PC has Java 17.",
            "required": 21,
            "installed": 17,
            "download": create_module.TEMURIN_URL,
        },
    )
    folder = tmp_path / "java-too-old"
    with pytest.raises(install_module.InstallError, match="needs Java 21"):
        await create_module.create_server(
            core,
            name="Old Java",
            directory=str(folder),
            type_id="vanilla",
            minecraft=MC,
            eula_accepted=True,
        )
    assert not folder.exists()
    assert java_module.required_java(MC) == 21


def test_the_default_memory_comes_from_the_pcs_real_memory():
    memory, reason = create_module.default_memory_mb()
    assert 2048 <= memory <= 8192
    assert "memory" in reason


# ---------------------------------------------------------------- crossplay
async def test_crossplay_installs_geyser_and_floodgate_with_floodgate_signin(ctx, network):
    status = crossplay.status(ctx)
    assert status["available"] is True
    assert status["enabled"] is False
    result = await crossplay.enable(ctx, user="tester")
    folder = ctx.config.mods_dir
    assert (folder / "Geyser-fabric.jar").is_file()
    assert (folder / "floodgate-fabric.jar").is_file()
    assert all(entry["verified"] for entry in result["downloaded"])
    config = Path(result["config"]).read_text(encoding="utf-8")
    assert "auth-type: floodgate" in config, "Bedrock players need no Java account"
    assert f"port: {result['port']}" in config
    assert ctx.config.server.crossplay is True
    assert crossplay.status(ctx)["ready"] is True


async def test_crossplay_picks_a_free_udp_port_and_avoids_a_clash(core, ctx, network):
    other = core.servers["creative"]
    await crossplay.enable(ctx, user="tester")
    first = ctx.config.server.bedrock_port
    assert first == crossplay.DEFAULT_BEDROCK_PORT or first > 0
    assert core.ports.used()[("udp", first)] == "survival"
    with pytest.raises(crossplay.CrossplayError, match="already used"):
        await crossplay.enable(other, port=first, user="tester")
    # A port of its own is fine.
    await crossplay.enable(other, port=first + 1, user="tester")
    assert core.ports.bedrock_port_of(other).port == first + 1


async def test_turning_crossplay_off_moves_the_files_aside(ctx, network):
    await crossplay.enable(ctx, user="tester")
    result = await crossplay.disable(ctx, user="tester")
    folder = ctx.config.mods_dir
    assert not (folder / "Geyser-fabric.jar").exists()
    assert (folder / "Geyser-fabric.jar.disabled").is_file(), "kept, not deleted"
    assert result["moved_aside"]
    assert ctx.config.server.crossplay is False
    assert crossplay.status(ctx)["ready"] is False


async def test_crossplay_is_refused_for_a_type_with_no_geyser_build(ctx, network):
    ctx.config.set("server.type", "vanilla")
    assert crossplay.available(ctx) is False
    assert crossplay.status(ctx)["unavailable_reason"]
    with pytest.raises(crossplay.CrossplayError, match="Geyser"):
        await crossplay.enable(ctx, user="tester")


async def test_crossplay_needs_the_server_stopped(ctx, network, monkeypatch):
    await ctx.server.start()
    assert await ctx.server.wait_online(timeout=20)
    try:
        with pytest.raises(crossplay.CrossplayError, match="Stop the server"):
            await crossplay.enable(ctx, user="tester")
    finally:
        await ctx.server.stop()


def test_a_bedrock_player_is_marked_by_floodgates_prefix_not_guessed(ctx):
    assert crossplay.is_bedrock_name(".PhoneFriend") is True
    assert crossplay.is_bedrock_name("JavaFriend") is False
    # With crossplay off every player came through the Java port.
    assert ctx.players.edition_of(".PhoneFriend") == "java"
    ctx.config.set("server.crossplay", True)
    assert ctx.players.edition_of(".PhoneFriend") == "bedrock"
    assert ctx.players.edition_of("JavaFriend") == "java"


async def test_a_bedrock_player_keeps_the_name_the_server_printed(ctx):
    ctx.config.set("server.crossplay", True)
    await ctx.players.player_joined(".PhoneFriend")
    online = ctx.players.online()
    assert [p["username"] for p in online] == [".PhoneFriend"]
    assert online[0]["edition"] == "bedrock"


# ---------------------------------------------------------------- the API
def test_the_type_table_lists_exactly_the_types_the_app_defines(multi_client):
    answer = multi_client.get("/api/server-types").json()
    assert {entry["id"] for entry in answer["types"]} == set(servertypes.TYPES)
    assert answer["recommended"] == "fabric"


def test_a_version_change_must_be_confirmed(multi_client):
    answer = multi_client.post("/api/servers/survival/version", json={"minecraft_version": MC})
    assert answer.status_code == 400
    assert "confirmed" in answer.json()["detail"]


def test_an_unknown_type_is_a_clear_error_from_the_api(multi_client):
    answer = multi_client.get("/api/server-types/fabrik/versions")
    assert answer.status_code == 400
    assert "fabrik" in answer.json()["detail"]


# ---------------------------------------------------------------- audit fixes
async def test_a_paper_backup_holds_its_plugins(ctx, network):
    """The default backup list predates plugins; each type adds what it keeps
    elsewhere, so a Paper server's plugins and their data are backed up."""
    ctx.config.set("server.type", "paper")
    plugins = ctx.config.server_dir / "plugins"
    (plugins / "Essentials").mkdir(parents=True)
    (plugins / "Essentials" / "userdata.yml").write_text("homes: {}", encoding="utf-8")
    backup = await ctx.backups.create(name="test", kind="manual", user="tester")
    row = ctx.backups.get(backup["id"])
    assert "plugins" in row["includes"].split(",")


def test_a_neoforge_mod_with_an_older_mods_toml_fits_neoforge(tmp_path):
    """NeoForge for Minecraft 1.20.2 to 1.20.4 used META-INF/mods.toml too;
    a mod that depends on neoforge is a NeoForge mod, not a Forge one."""
    import zipfile

    from agent.mods.jarinfo import read_mod_jar, wrong_loader_reason

    jar = tmp_path / "neo.jar"
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr(
            "META-INF/mods.toml",
            'modLoader="javafml"\nloaderVersion="[2,)"\n[[mods]]\nmodId="neo"\n'
            'version="1.0"\n[[dependencies.neo]]\nmodId="neoforge"\ntype="required"\n'
            'versionRange="[20.4,)"\nside="BOTH"\n',
        )
    info = read_mod_jar(jar)
    assert info.loaders == ["neoforge"]
    neoforge = servertypes.get("neoforge")
    assert wrong_loader_reason(info, neoforge.accepts, neoforge.name) is None


def test_a_eula_file_saying_false_shows_the_accept_button(ctx):
    """The server refuses to start without eula=true, so it never prints
    the EULA line; the file itself has to raise the question."""
    (ctx.config.server_dir / "eula.txt").write_text("eula=false\n", encoding="utf-8")
    assert ctx.server.status()["eula_required"] is True
    (ctx.config.server_dir / "eula.txt").write_text("#eula=true\neula=true\n", encoding="utf-8")
    assert ctx.server.status()["eula_required"] is False


@pytest.mark.parametrize(
    "type_id, folder",
    [
        ("fabric", "config/Geyser-Fabric"),
        ("neoforge", "config/Geyser-NeoForge"),
        ("paper", "plugins/Geyser-Spigot"),
    ],
)
def test_geysers_settings_go_where_each_build_reads_them(ctx, type_id, folder):
    ctx.config.set("server.type", type_id)
    path = crossplay.write_geyser_config(ctx, 19133)
    assert path == ctx.config.server_dir / folder / "config.yml"


async def test_crossplay_leaves_nothing_behind_when_floodgate_is_missing(ctx, network, monkeypatch):
    real = crossplay._latest

    async def no_floodgate(platform, project):
        if project == "floodgate":
            raise crossplay.CrossplayError("GeyserMC doesn't publish floodgate for fabric servers")
        return await real(platform, project)

    monkeypatch.setattr(crossplay, "_latest", no_floodgate)
    with pytest.raises(crossplay.CrossplayError):
        await crossplay.enable(ctx)
    assert not list(ctx.config.mods_dir.glob("Geyser*"))
    assert ctx.config.server.crossplay is False


async def test_the_preflight_names_mods_that_say_they_dont_support_the_target(ctx, network):
    make_jar(ctx.config.mods_dir / "old.jar", "old", "1.0", depends={"minecraft": "1.20.1"})
    report = await install_module.preflight(ctx, "fabric", MC)
    assert report["not_supporting"] == ["old.jar"]


def test_an_existing_paper_folder_can_be_added_as_paper(multi_client, multi, tmp_path):
    folder = tmp_path / "Lobby"
    folder.mkdir()
    (folder / "paper.jar").write_bytes(SERVER_JAR)
    response = multi_client.post(
        "/api/servers", json={"name": "Lobby", "directory": str(folder), "type": "paper"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["server"]["type"] == "paper"
    assert multi.for_server("lobby").server.jar == "paper.jar"
    assert multi.for_server("lobby").mods_dir.name == "plugins"


def test_an_existing_forge_folder_needs_its_start_file(multi_client, multi, tmp_path):
    folder = tmp_path / "Modded"
    folder.mkdir()
    response = multi_client.post(
        "/api/servers", json={"name": "Modded", "directory": str(folder), "type": "forge"}
    )
    assert response.status_code == 400
    assert "start file" in response.json()["detail"]
    target = folder / "libraries" / "net" / "minecraftforge" / "forge" / "1.20.1-47.3.0"
    target.mkdir(parents=True)
    wanted = "win_args.txt" if os.name == "nt" else "unix_args.txt"
    (target / wanted).write_text("-p a.jar", encoding="utf-8")
    response = multi_client.post(
        "/api/servers", json={"name": "Modded", "directory": str(folder), "type": "forge"}
    )
    assert response.status_code == 200, response.text
    assert multi.for_server("modded").server.args_file.endswith(wanted)
