"""Automatic restart countdown: RESTART_PENDING, Restart Now, Cancel, and the
guarantee that concurrent requests can never launch two Minecraft processes."""

import asyncio
import time

import pytest

from agent.events import EventBus
from agent.minecraft.process import MinecraftServer, ServerError
from agent.minecraft.state import ServerState


def make(make_config, delay=30.0):
    config = make_config(**{"monitor.auto_restart": True, "monitor.restart_delay": delay,
                            "monitor.max_crashes": 10})
    bus = EventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    return MinecraftServer(config, bus), events


def launches(events):
    """How many times the server actually entered STARTING."""
    return len([e for e in events if e.type == "state" and e.data.get("state") == "STARTING"])


async def crash(server):
    await server.start()
    assert await server.wait_online(timeout=20)
    await server.send_command("crash")
    for _ in range(100):
        await asyncio.sleep(0.05)
        if server.state is ServerState.RESTART_PENDING:
            return
    raise AssertionError(f"never reached RESTART_PENDING (state {server.state})")


async def test_crash_enters_restart_pending_with_an_authoritative_deadline(make_config):
    server, events = make(make_config, delay=30)
    await crash(server)
    status = server.status()
    assert status["state"] == "RESTART_PENDING"
    assert 25 < status["restart_in"] <= 30
    assert abs(status["restart_at"] - (time.time() + status["restart_in"])) < 1
    assert any(e.type == "restart_scheduled" for e in events)
    await server.cancel_pending_restart()


async def test_countdown_reaching_zero_starts_the_server(make_config):
    server, events = make(make_config, delay=0.5)
    await crash(server)
    assert await server.wait_online(timeout=20)
    for _ in range(60):
        await asyncio.sleep(0.05)
        if any(e.type == "server_recovered" for e in events):
            break
    types = [e.type for e in events]
    assert "restart_started" in types
    assert "server_recovered" in types
    assert server.status()["restart_at"] is None
    await server.stop()


async def test_restart_now_skips_the_countdown(make_config):
    server, events = make(make_config, delay=60)
    await crash(server)
    before = launches(events)
    await server.restart_now(actor="tester")
    assert await server.wait_online(timeout=20)
    assert launches(events) == before + 1
    assert any(e.type == "restart_forced" for e in events)
    await asyncio.sleep(0.3)
    assert launches(events) == before + 1, "the cancelled timer must not launch a second process"
    await server.stop()


async def test_cancel_keeps_the_server_stopped(make_config):
    server, events = make(make_config, delay=1.0)
    await crash(server)
    await server.cancel_pending_restart(actor="tester")
    assert server.state is ServerState.CRASHED
    assert server.status()["auto_restart_cancelled"] is True
    assert server.status()["restart_at"] is None
    await asyncio.sleep(1.6)   # past the original deadline
    assert server.state is ServerState.CRASHED, "a cancelled restart must not fire"
    assert any(e.type == "restart_cancelled" for e in events)


async def test_normal_start_is_refused_during_the_countdown(make_config):
    server, _ = make(make_config, delay=30)
    await crash(server)
    with pytest.raises(ServerError, match="automatic restart is already scheduled"):
        await server.start(actor="tester")
    assert server.state is ServerState.RESTART_PENDING
    await server.cancel_pending_restart()


async def test_concurrent_requests_launch_exactly_one_process(make_config):
    server, events = make(make_config, delay=60)
    await crash(server)
    before = launches(events)
    results = await asyncio.gather(
        server.restart_now("a"), server.restart_now("b"), server.start("c"),
        server.cancel_pending_restart("d"), return_exceptions=True)
    await asyncio.sleep(0.5)
    assert launches(events) - before <= 1, f"{launches(events) - before} launches for 4 requests"
    assert sum(1 for r in results if isinstance(r, ServerError)) >= 3
    if server.running:
        await server.wait_online(timeout=20)
        await server.stop()


async def test_restart_now_and_cancel_need_a_pending_restart(make_config):
    server, _ = make(make_config)
    for call in (server.restart_now, server.cancel_pending_restart):
        with pytest.raises(ServerError, match="No automatic restart is pending"):
            await call("tester")


async def test_cancel_is_refused_once_the_restart_is_already_launching(make_config):
    """Interrupting a half-finished start could orphan a process."""
    server, _ = make(make_config)
    server.state = ServerState.RESTART_PENDING
    server._restart_task = asyncio.create_task(asyncio.sleep(5))
    server._restart_sleeping = False           # the countdown has finished
    try:
        with pytest.raises(ServerError, match="already starting"):
            await server.cancel_pending_restart()
    finally:
        server._restart_task.cancel()


def test_restart_endpoints_report_conflicts_in_plain_language(config, monkeypatch):
    from fastapi.testclient import TestClient
    from agent.main import create_app
    from agent.security.auth import hash_password
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password("long enough password", rounds=1000))
    with TestClient(create_app(config)) as client:
        token = client.post("/api/auth/login", json={"username": "admin",
                                                     "password": "long enough password"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        for path in ("/api/server/restart-now", "/api/server/cancel-restart"):
            response = client.post(path, headers=headers)
            assert response.status_code == 409
            assert "No automatic restart is pending" in response.json()["detail"]
        assert client.post("/api/server/restart-now").status_code == 401


async def test_mod_changes_are_refused_during_the_countdown(make_config):
    """A restart firing while a jar is half-written could corrupt the install."""
    from agent.database.db import Database
    from agent.mods.manager import ModError, ModManager
    server, _ = make(make_config, delay=30)
    db = Database(server.config.database_path)
    mods = ModManager(server.config, server.bus, db, server)
    await crash(server)
    with pytest.raises(ModError, match="Cancel it before"):
        mods._require_server_offline("install a mod")
    await server.cancel_pending_restart()
    mods._require_server_offline("install a mod")   # allowed once cancelled
