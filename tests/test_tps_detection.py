"""Automatic TPS detection against a fake server that behaves like each
provider, and rejects the others' commands the way a real server does."""

import asyncio
import os

import pytest

from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.console import parse_line
from agent.minecraft.process import MinecraftServer
from agent.monitoring import tps as tps_module
from agent.monitoring.tps import TpsMonitor, candidates_for


@pytest.fixture
def setup(config, monkeypatch):
    monkeypatch.setattr(tps_module, "PROBE_TIMEOUT", 2.0)
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    monitor = TpsMonitor(config, bus, db, server)
    return config, bus, db, server, monitor


async def online(server, provider):
    os.environ["FAKE_TPS_PROVIDER"] = provider
    await server.start()
    assert await server.wait_online(timeout=20)


async def finish(server):
    os.environ.pop("FAKE_TPS_PROVIDER", None)
    if server.running:
        await server.stop()


@pytest.mark.parametrize(
    "provider,expected", [("tick", "tick query"), ("carpet", "tps"), ("spark", "spark tps")]
)
async def test_each_provider_is_detected(setup, provider, expected):
    config, bus, db, server, monitor = setup
    await online(server, provider)
    try:
        result = await monitor.detect()
        assert result["state"] == "active"
        assert result["command"] == expected
        assert result["detection"] == "automatic"
        assert server.tps is not None
        # every command tried before the working one was rejected, not guessed at
        for tried in result["tried"][:-1]:
            assert tried["result"] == "rejected"
        assert db.get_setting("tps_detected")["command"] == expected
    finally:
        await finish(server)


async def test_vanilla_tps_comes_from_measured_tick_time_not_the_target(setup, monkeypatch):
    config, bus, db, server, monitor = setup
    monkeypatch.setenv("FAKE_MSPT", "80.0")  # an overloaded server
    await online(server, "tick")
    try:
        await monitor.detect()
        assert server.mspt == 80.0
        assert server.tps == 12.5, "20.0 is the target rate; the measured rate is 1000/80"
    finally:
        await finish(server)


async def test_no_provider_reports_unavailable_with_the_reason(setup):
    config, bus, db, server, monitor = setup
    await online(server, "none")
    try:
        result = await monitor.detect()
        assert result["state"] == "unavailable"
        assert result["command"] is None
        assert [t["command"] for t in result["tried"]] == ["tick query", "tps", "spark tps"]
        assert all(t["result"] == "rejected" for t in result["tried"])
        assert "Carpet or spark" in result["message"]
        assert server.tps is None, "nothing answered, so TPS must stay unknown"
        assert "does not appear to support" in server.tps_unavailable_reason()
    finally:
        await finish(server)


async def test_a_remembered_command_is_tried_first(setup):
    config, bus, db, server, monitor = setup
    db.set_setting("tps_detected", {"command": "spark tps"})
    await online(server, "spark")
    try:
        result = await monitor.detect()
        assert result["tried"][0]["command"] == "spark tps"
        assert len(result["tried"]) == 1, "no other command should be sent"
        assert result["detection"] == "remembered"
    finally:
        await finish(server)


async def test_manual_override_is_used_and_verified(setup):
    config, bus, db, server, monitor = setup
    await online(server, "carpet")
    try:
        await monitor.set_command("tps")
        await asyncio.sleep(0.1)
        result = await monitor.detect()
        assert result["mode"] == "manual"
        assert result["detection"] == "manual"
        assert [t["command"] for t in result["tried"]] == ["tps"]
        assert config.get("monitor.tps_command") == "tps"
    finally:
        await monitor.halt()
        await finish(server)


async def test_a_manual_command_that_does_not_answer_is_reported(setup):
    config, bus, db, server, monitor = setup
    config.set("monitor.tps_command", "spark tps")
    await online(server, "tick")
    try:
        result = await monitor.detect()
        assert result["state"] == "unavailable"
        assert "did not report TPS" in result["message"]
    finally:
        await finish(server)


async def test_dangerous_or_invalid_override_is_refused(setup):
    config, bus, db, server, monitor = setup
    for bad in ("stop", "op Steve", "tps; shutdown", "tps\nstop"):
        with pytest.raises(ValueError):
            await monitor.set_command(bad)


async def test_detection_runs_once_per_server_start(setup, monkeypatch):
    config, bus, db, server, monitor = setup
    config.set("monitor.tps_poll_interval", 600)
    bus.subscribe(monitor.handle)
    sent = []
    original = server.send_command

    async def counting(command, internal=False):
        sent.append(command)
        return await original(command, internal=internal)

    monkeypatch.setattr(server, "send_command", counting)
    await online(server, "tick")
    try:
        for _ in range(80):
            await asyncio.sleep(0.1)
            if monitor.status()["state"] == "active":
                break
        await asyncio.sleep(1.0)
        assert monitor.status()["state"] == "active"
        assert sent.count("tick query") == 1, f"probed {sent.count('tick query')} times"
        assert sent == ["tick query"]
    finally:
        await monitor.halt()
        await finish(server)


async def test_stopping_the_server_resets_detection(setup):
    config, bus, db, server, monitor = setup
    await online(server, "tick")
    await monitor.detect()
    await finish(server)
    await monitor.halt()
    assert monitor.status()["state"] == "idle"
    assert monitor.status()["command"] is None


def test_tick_query_is_not_sent_to_servers_older_than_1_20_3():
    assert "tick query" not in candidates_for("1.19.4")
    assert "tick query" not in candidates_for("1.20.2")
    assert candidates_for("1.20.4")[0] == "tick query"
    assert "tick query" in candidates_for(None), "unknown version: worth one try"
    assert candidates_for("1.21", remembered="spark tps")[0] == "spark tps"


async def test_redetect_needs_an_online_server(setup):
    config, bus, db, server, monitor = setup
    with pytest.raises(ValueError, match="Start the server first"):
        await monitor.redetect()


async def test_target_rate_line_alone_never_sets_tps(setup):
    config, bus, db, server, monitor = setup
    await server._handle_signals(
        parse_line("[10:00:00] [Server thread/INFO]: Target tick rate: 20.0 per second.", 1)
    )
    assert server.tps is None
