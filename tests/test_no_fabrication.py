"""The no-fabrication rule, enforced as tests.

Each test removes a data source and asserts the system says "unknown" rather
than producing a plausible number. These are the tests that fail if someone
later adds a convenient default.
"""

import pytest

from agent.backups.manager import BackupError, BackupManager
from agent.core import AgentCore
from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.analyzer import analyze
from agent.minecraft.java import JavaInfo, check_compatibility, detect_java, required_java
from agent.minecraft.process import MinecraftServer
from agent.minecraft.state import ServerState
from agent.mods.manager import ModManager
from agent.monitoring.metrics import MetricsMonitor
from agent.monitoring.players import PlayerTracker

from .test_mods import make_jar


@pytest.fixture
def parts(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return config, bus, db, server


# ---------------------------------------------------------------- state
def test_state_is_unknown_before_anything_is_checked(parts):
    config, bus, db, server = parts
    assert server.state is ServerState.UNKNOWN
    status = server.status()
    assert status["state"] == "UNKNOWN"
    assert status["state_verified"] is False
    assert status["state_source"] == "not checked"


def test_state_becomes_offline_only_after_verification(parts):
    config, bus, db, server = parts
    assert server.verify_state() is ServerState.OFFLINE
    assert server.status()["state_verified"] is True
    assert "exit" in server.status()["state_source"] or "process" in server.status()["state_source"]


async def test_online_is_only_claimed_after_the_startup_line(config):
    """Launching the process is not being online."""
    bus = EventBus()
    server = MinecraftServer(config, bus)
    import os

    os.environ["FAKE_BOOT_DELAY"] = "2"
    try:
        await server.start()
        assert server.state is ServerState.STARTING
        assert server.startup_confirmed is False
        assert server.status()["state"] != "ONLINE"
        assert await server.wait_online(timeout=20)
        assert server.startup_confirmed is True
        assert server.state is ServerState.ONLINE
    finally:
        os.environ.pop("FAKE_BOOT_DELAY", None)
        if server.running:
            await server.stop()


# ---------------------------------------------------------------- TPS / MSPT
def test_tps_is_unknown_with_no_provider(parts):
    config, bus, db, server = parts
    assert server.tps is None
    assert server.mspt is None
    status = server.status()
    assert status["tps"] is None
    assert status["mspt"] is None
    assert status["tps_source"] is None
    assert "not online" in status["tps_unavailable_reason"]


def test_tps_reason_names_the_command_that_went_unanswered(parts):
    config, bus, db, server = parts
    config.set("monitor.tps_command", "tps")  # a manual command that never answered
    server.state = ServerState.ONLINE
    server.tps_asked_at = 1.0
    reason = server.tps_unavailable_reason()
    assert "tps" in reason
    assert "Carpet" in reason or "spark" in reason


def test_tps_records_its_source_when_a_provider_answers(parts):
    config, bus, db, server = parts
    from agent.minecraft.console import parse_line

    import asyncio

    line = parse_line("[10:00:00] [Server thread/INFO]: TPS: 19.8 MSPT: 12.400", 1)
    asyncio.get_event_loop().run_until_complete(server._handle_signals(line)) if False else None
    asyncio.run(server._handle_signals(line))
    assert server.tps == 19.8
    assert server.mspt == 12.4
    assert server.tps_source
    assert server.tps_unavailable_reason() is None


def test_health_reports_unknown_tps_and_partial_verification(parts):
    config, bus, db, server = parts
    metrics = MetricsMonitor(config, bus, db, server)
    health = metrics.health(player_count=None)
    tps = next(c for c in health["checks"] if c["name"] == "TPS")
    assert tps["status"] == "unknown"
    assert tps["value"] is None
    assert health["overall"] in ("PARTIALLY VERIFIED", "ATTENTION NEEDED")
    assert "TPS" in health["unverified"]


def test_no_health_check_claims_ok_without_a_source(parts):
    config, bus, db, server = parts
    metrics = MetricsMonitor(config, bus, db, server)
    for check in metrics.health()["checks"]:
        if check["status"] == "ok":
            assert check["source"], f"{check['name']} reports ok with no stated source"


# ---------------------------------------------------------------- players
def test_player_count_is_unknown_before_any_evidence(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    assert tracker.verified is False
    assert tracker.online_count() is None, "an empty list is not a verified zero"


async def test_player_count_becomes_zero_only_once_verified(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    await tracker.clear_online()
    assert tracker.verified is True
    assert tracker.online_count() == 0
    assert "not running" in tracker.verified_source


async def test_player_count_is_verified_by_a_join(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    await tracker.player_joined("Steve")
    assert tracker.online_count() == 1
    assert "join" in tracker.verified_source


# ---------------------------------------------------------------- versions
def test_minecraft_and_fabric_versions_start_unknown(parts):
    config, bus, db, server = parts
    status = server.status()
    assert status["minecraft_version"] is None
    assert status["minecraft_version_source"] is None
    assert status["fabric_loader"] is None


def test_versions_are_only_set_from_console_output(parts):
    config, bus, db, server = parts
    import asyncio
    from agent.minecraft.console import parse_line

    line = parse_line(
        "[10:00:00] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.3", 1
    )
    asyncio.run(server._handle_signals(line))
    status = server.status()
    assert status["minecraft_version"] == "1.20.1"
    assert status["minecraft_version_source"] == "server console"
    assert status["fabric_loader"] == "0.15.3"


# ---------------------------------------------------------------- java
def test_java_detection_reports_unknown_for_a_missing_executable():
    info = detect_java("definitely-not-java-12345")
    assert info.executable_found is False
    assert info.version_major is None
    assert info.error


def test_java_detection_reads_a_real_executable():
    """Uses python itself as a stand-in binary: the point is that an
    unparseable -version output yields unknown, not a guess."""
    import sys

    info = detect_java(sys.executable)
    assert info.executable_found is True
    assert info.version_major is None or isinstance(info.version_major, int)


def test_compatibility_is_unknown_when_java_version_is_unknown():
    verdict = check_compatibility(JavaInfo(version_major=None, error="could not parse"), "1.20.1")
    assert verdict["verdict"] == "unknown"


def test_compatibility_is_unknown_when_minecraft_version_is_unknown():
    verdict = check_compatibility(JavaInfo(version_major=21), None)
    assert verdict["verdict"] == "unknown"
    assert "not known yet" in verdict["detail"]


def test_compatibility_verdicts_when_both_are_known():
    assert check_compatibility(JavaInfo(version_major=21), "1.21.1")["verdict"] == "compatible"
    assert check_compatibility(JavaInfo(version_major=17), "1.21.1")["verdict"] == "incompatible"
    assert check_compatibility(JavaInfo(version_major=17), "1.19.2")["verdict"] == "compatible"
    assert required_java("1.20.6") == 21
    assert required_java("1.18.2") == 17
    assert required_java(None) is None


# ---------------------------------------------------------------- crash
def test_crash_cause_is_unknown_when_nothing_matches():
    result = analyze(["[10:00:00] [Server thread/INFO]: nothing useful here"], exit_code=1)
    assert result.category == "Unknown"
    assert result.confidence == "unknown"
    assert "No known pattern matched" in result.evidence_basis
    assert result.suspect_mods == [] or all(isinstance(m, str) for m in result.suspect_mods)


def test_confidence_tiers_are_distinguished():
    confirmed = analyze(["java.lang.OutOfMemoryError: Java heap space"])
    likely = analyze(["org.spongepowered.asm.mixin.injection.throwables.InjectionError: x"])
    possible = analyze(["java.net.SocketException: Connection reset by peer"])
    assert confirmed.confidence == "confirmed"
    assert likely.confidence == "likely"
    assert possible.confidence == "possible"


def test_analysis_always_carries_its_evidence_and_a_disclaimer():
    result = analyze(["java.lang.OutOfMemoryError: Java heap space"]).to_dict()
    assert result["evidence"]
    assert "pattern match" in result["disclaimer"]


def test_a_mod_is_never_named_as_the_cause():
    lines = [
        "[10:00:00] [Server thread/ERROR]: Exception in server tick loop",
        "\tat com.example.voxy.Renderer.tick(Renderer.java:42)",
    ]
    result = analyze(lines, exit_code=1, known_mod_ids=["voxy"])
    assert "voxy" in result.suspect_mods
    # the category is the error class, never the mod name
    assert result.category != "voxy"
    assert "voxy" not in result.summary


# ---------------------------------------------------------------- backups
@pytest.fixture
def backups(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return BackupManager(config, bus, db, server)


async def test_backup_success_is_only_claimed_after_verification(backups, config):
    result = await backups.create(user="tester")
    assert result["verified"] is True
    assert result["verification"]["entries"] > 0
    assert "SHA-256 match" in result["verification"]["checks"]


async def test_a_backup_that_fails_verification_is_not_reported_as_ok(backups, config, monkeypatch):
    """Simulate a truncated archive: the row must not say ok."""

    def broken(path, expected_sha256=None, expected_files=None):
        return {"ok": False, "reason": "simulated truncation"}

    monkeypatch.setattr(backups, "_verify_file", broken)
    with pytest.raises(BackupError, match="failed verification"):
        await backups.create(user="tester")
    row = backups.list_backups()[0]
    assert row["status"] == "unverified"
    assert "FAILED VERIFICATION" in row["note"]


async def test_restore_is_only_reported_when_files_are_actually_back(backups, config):
    marker = config.server_dir / "world" / "marker.dat"
    marker.write_text("original")
    created = await backups.create(user="tester")
    marker.write_text("changed")
    result = await backups.restore(created["id"], user="tester")
    assert result["verified"] is True
    assert "checked" in result["verification"]
    assert marker.read_text() == "original"


# ---------------------------------------------------------------- mods
@pytest.fixture
def mods(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return ModManager(config, bus, db, server)


async def test_installing_a_mod_does_not_claim_it_is_loaded(mods, config, tmp_path):
    source = make_jar(tmp_path / "build.jar", "cooltech", "2.1.0")
    result = await mods.install_local_file("cooltech-2.1.0.jar", source.read_bytes(), user="tester")
    assert result["loaded_by_minecraft"] == "not verified"
    assert "Start the server" in result["loaded_detail"]


def test_compatibility_is_unknown_without_a_detected_minecraft_version(mods, config):
    verdict = mods.compatibility_verdict({"game_versions": ["1.20.1"]}, None)
    assert verdict["verdict"] == "unknown"
    assert "not been observed" in verdict["detail"]


def test_modrinth_listing_alone_is_only_likely(mods, config):
    mods.server.mc_version = "1.20.1"
    verdict = mods.compatibility_verdict({"game_versions": ["1.20.1"]}, None)
    assert verdict["verdict"] == "likely"
    assert "publisher's claim" in verdict["detail"]


def test_declared_metadata_gives_the_strongest_available_verdict(mods, config):
    mods.server.mc_version = "1.20.1"
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0", depends={"minecraft": ">=1.20"})
    mod = mods.find("cooltech.jar")
    verdict = mods.compatibility_verdict({"game_versions": ["1.20.1"]}, mod)
    assert verdict["verdict"] == "verified_metadata"
    assert "not a test" in verdict["detail"]


def test_clean_mod_check_does_not_claim_there_are_no_conflicts(mods, config):
    make_jar(config.mods_dir / "solo.jar", "solo", "1.0.0")
    checks = mods.check_all()
    assert checks["problems"] == []
    assert checks["claim"] == "No declared conflicts detected"
    assert "is not the same as" in checks["claim_note"]


# ---------------------------------------------------------------- disk space
def _unreadable_disk(path):
    raise OSError("drive not ready")


def test_disk_free_is_unknown_when_the_server_drive_cannot_be_read(parts, monkeypatch):
    """Never report another drive's free space (such as the home folder's)."""
    config, bus, db, server = parts
    monkeypatch.setattr("agent.monitoring.metrics.shutil.disk_usage", _unreadable_disk)
    metrics = MetricsMonitor(config, bus, db, server)
    snap = metrics.snapshot()
    assert snap["disk_free_gb"] is None
    assert snap["disk_total_gb"] is None
    assert snap["disk_percent"] is None
    assert "drive not ready" in snap["disk_unknown_reason"]
    disk = next(c for c in metrics.health()["checks"] if c["name"] == "Disk space")
    assert disk["status"] == "unknown"
    assert disk["value"] is None


def test_storage_free_space_is_unknown_not_zero_when_the_query_fails(parts, monkeypatch):
    config, bus, db, server = parts
    monkeypatch.setattr("agent.monitoring.metrics.shutil.disk_usage", _unreadable_disk)
    storage = MetricsMonitor(config, bus, db, server).storage_breakdown()
    assert storage["free_gb"] is None, "a failed check must not read as 0 GB free"
    assert "drive not ready" in storage["free_unknown_reason"]


async def test_unknown_disk_space_raises_no_low_disk_alert(parts, monkeypatch):
    config, bus, db, server = parts
    monkeypatch.setattr("agent.monitoring.metrics.shutil.disk_usage", _unreadable_disk)
    seen = []
    bus.subscribe(lambda event: seen.append(event.type))
    await MetricsMonitor(config, bus, db, server).sample_once(player_count=0)
    assert "low_disk" not in seen


# ---------------------------------------------------------------- tailscale / TLS
def test_tailscale_is_unknown_when_the_cli_cannot_be_asked(parts, monkeypatch):
    config, bus, db, server = parts
    monkeypatch.setattr("agent.tailscale.tailscale_binary", lambda: None)
    monkeypatch.setattr("psutil.net_if_addrs", lambda: {})
    metrics = MetricsMonitor(config, bus, db, server)
    status = metrics.tailscale_status()
    assert status["connected"] is None
    assert status["verified"] is False


def test_an_address_alone_does_not_prove_tailscale_connectivity(parts, monkeypatch):
    config, bus, db, server = parts
    import socket as socket_module
    from collections import namedtuple

    Addr = namedtuple("Addr", "family address netmask broadcast ptp")
    monkeypatch.setattr("agent.tailscale.tailscale_binary", lambda: None)
    monkeypatch.setattr(
        "psutil.net_if_addrs",
        lambda: {"Tailscale": [Addr(socket_module.AF_INET, "100.101.102.103", None, None, None)]},
    )
    metrics = MetricsMonitor(config, bus, db, server)
    status = metrics.tailscale_status()
    assert status["connected"] is None, "an assigned address is not proof of connectivity"
    assert status["address"] == "100.101.102.103"
    assert "could not be confirmed" in status["detail"]


def test_certificate_status_is_unknown_when_the_file_is_missing(parts):
    config, bus, db, server = parts
    config.set("tls.enabled", True)
    metrics = MetricsMonitor(config, bus, db, server)
    status = metrics.certificate_status()
    assert status["certificate_present"] is False
    assert status["days_remaining"] is None
    assert status["expiry_severity"] == "unknown"


async def test_certificate_problem_raises_an_event_rather_than_a_false_ok(config, monkeypatch):
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", "x")
    config.set("tls.enabled", True)
    core = AgentCore(config)
    seen = []
    core.bus.subscribe(lambda event: seen.append(event.type))
    try:
        status = await core.check_certificate()
        assert status["parsed"] is False
        assert "certificate_problem" in seen
    finally:
        core.db.close()


# ---------------------------------------------------------------- API shape
def test_control_responses_distinguish_requested_from_verified():
    """The route layer must not collapse 'sent' into 'succeeded'."""
    from .conftest import api_routes_source

    source = api_routes_source()
    assert '"result": "REQUESTED"' in source
    assert '"result": "VERIFIED" if stopped else "IN_PROGRESS"' in source
    assert '"ok": True, **result, "state": core.server.state.value' not in source


# ---------------------------------------------------------------- no guessed paths
def test_the_server_folder_has_no_built_in_default():
    from agent.config import DEFAULTS

    assert DEFAULTS["server"]["directory"] == "", "no machine-specific path may ship as a default"


def test_an_unset_server_folder_is_never_the_working_directory(tmp_path, monkeypatch):
    from agent.config import DEFAULTS, Config, _deep_merge

    monkeypatch.chdir(tmp_path)
    cfg = Config(_deep_merge(DEFAULTS, {}))
    assert cfg.server_dir_configured is False
    assert not cfg.server_dir.exists(), "Path('') would have meant the current directory"
    assert cfg.server_dir.resolve() != tmp_path.resolve()
    assert tmp_path not in cfg.data_dir.parents and cfg.data_dir != tmp_path


def test_starting_with_an_unset_folder_explains_what_to_do(tmp_path):
    from agent.config import DEFAULTS, Config, _deep_merge

    server = MinecraftServer(
        Config(_deep_merge(DEFAULTS, {"paths": {"data_dir": str(tmp_path)}})), EventBus()
    )
    result = server.preflight()
    assert result.ok is False
    assert "server.directory" in result.problems[0]


def test_mod_manager_refuses_to_create_folders_for_an_unset_server(tmp_path):
    from agent.config import DEFAULTS, Config, _deep_merge
    from agent.mods.manager import ModError

    cfg = Config(_deep_merge(DEFAULTS, {"paths": {"data_dir": str(tmp_path)}}))
    db = Database(cfg.database_path)
    manager = ModManager(cfg, EventBus(), db, MinecraftServer(cfg, EventBus(), db))
    with pytest.raises(ModError, match="server.directory"):
        manager.scan()
    assert not cfg.server_dir.exists()


def test_diagnostics_create_nothing_for_an_unset_server_folder(tmp_path):
    from agent.config import DEFAULTS, Config, _deep_merge
    from agent.diagnostics import run_diagnostics

    cfg = Config(
        _deep_merge(
            DEFAULTS, {"paths": {"data_dir": str(tmp_path / "data")}, "tls": {"enabled": False}}
        )
    )
    report = run_diagnostics(cfg)
    assert any(c.name == "Minecraft directory" and c.status == "FAIL" for c in report.failures)
    assert not cfg.server_dir.exists(), "the diagnostic must not create the placeholder folder"


def test_diagnostics_never_report_another_drives_free_space(tmp_path):
    from agent.config import DEFAULTS, Config, _deep_merge
    from agent.diagnostics import Report, _storage

    cfg = Config(
        _deep_merge(
            DEFAULTS,
            {
                "server": {"directory": str(tmp_path / "missing")},
                "paths": {"data_dir": str(tmp_path / "data")},
                "tls": {"enabled": False},
            },
        )
    )
    report = Report()
    _storage(report, cfg)
    disk = next(c for c in report.sections["Storage"] if c.name == "Disk space")
    assert disk.status == "UNKNOWN"
    assert "GB" not in disk.value
