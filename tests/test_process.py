import asyncio
import os

import pytest

from agent.events import EventBus
from agent.minecraft.process import MinecraftServer, ServerError
from agent.minecraft.state import ExitReason, ServerState


def collector(bus):
    seen = []
    bus.subscribe(lambda e: seen.append(e))
    return seen


async def test_start_reaches_online_and_reports_versions(config):
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start(actor="tester")
    assert await server.wait_online(timeout=15)
    assert server.state is ServerState.ONLINE
    assert server.pid
    assert server.mc_version == "1.21.1"
    assert server.loader_version == "0.16.5"
    await server.stop(actor="tester")
    assert server.state is ServerState.OFFLINE


async def test_graceful_stop_is_not_a_crash(config):
    bus = EventBus()
    events = collector(bus)
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=15)
    result = await server.stop(actor="tester")
    assert result["graceful"] is True
    assert server.state is ServerState.OFFLINE
    assert server.last_exit_reason is ExitReason.USER_STOP
    assert not [e for e in events if e.type == "server_crashed"]
    assert [e for e in events if e.type == "server_stopped"]


async def test_crash_is_detected_with_exit_code(config):
    bus = EventBus()
    events = collector(bus)
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=15)
    await server.send_command("crash")
    assert await server.wait_exit(timeout=15)
    await asyncio.sleep(0.2)
    assert server.state is ServerState.CRASHED
    assert server.last_exit_reason is ExitReason.CRASH
    assert server.last_exit_code == 1
    assert [e for e in events if e.type == "server_crashed"]


async def test_startup_failure_is_distinct_from_crash(config):
    os.environ["FAKE_CRASH_ON_START"] = "1"
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    assert not await server.wait_online(timeout=5)
    assert await server.wait_exit(timeout=10)
    assert server.state is ServerState.CRASHED
    assert server.last_exit_reason is ExitReason.STARTUP_FAILURE


async def test_restart_brings_server_back(config):
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=15)
    first_pid = server.pid
    await server.restart(actor="tester")
    assert await server.wait_online(timeout=15)
    assert server.state is ServerState.ONLINE
    assert server.pid != first_pid
    await server.stop()


async def test_force_kill_when_stop_times_out(make_config):
    config = make_config(**{"server.stop_timeout": 1})
    os.environ["FAKE_HANG"] = "1"
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    await asyncio.sleep(1.0)
    result = await server.stop(actor="tester", timeout=1)
    assert result["graceful"] is False
    assert server.last_exit_reason is ExitReason.FORCE_KILLED
    assert server.state is ServerState.OFFLINE


async def test_auto_restart_after_crash(make_config):
    config = make_config(**{"monitor.auto_restart": True, "monitor.restart_delay": 0.2})
    bus = EventBus()
    events = collector(bus)
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=15)
    await server.send_command("crash")
    for _ in range(200):
        await asyncio.sleep(0.1)
        if server.state is ServerState.ONLINE:
            break
    assert server.state is ServerState.ONLINE
    assert [e for e in events if e.type == "server_recovered"]
    await server.stop()


async def test_crash_loop_protection_blocks_restart(make_config):
    config = make_config(
        **{
            "monitor.auto_restart": True,
            "monitor.restart_delay": 0.05,
            "monitor.max_crashes": 2,
            "monitor.crash_window_minutes": 10,
        }
    )
    os.environ["FAKE_CRASH_ON_START"] = "1"
    bus = EventBus()
    events = collector(bus)
    server = MinecraftServer(config, bus)
    await server.start()
    for _ in range(200):
        await asyncio.sleep(0.1)
        if server.auto_restart_blocked:
            break
    assert server.auto_restart_blocked is True
    assert "crashes within" in (server.auto_restart_block_reason or "")
    assert [e for e in events if e.type == "crash_loop"]


async def test_commands_require_running_server(config):
    bus = EventBus()
    server = MinecraftServer(config, bus)
    with pytest.raises(ServerError):
        await server.send_command("say hi")


async def test_newline_injection_is_refused(config):
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=15)
    with pytest.raises(ServerError):
        await server.send_command("say hi\nstop")
    assert server.state is ServerState.ONLINE
    await server.stop()


async def test_preflight_reports_missing_jar(make_config):
    config = make_config(**{"server.raw_command": None, "server.jar": "does-not-exist.jar"})
    bus = EventBus()
    server = MinecraftServer(config, bus)
    result = server.preflight()
    assert result.ok is False
    assert any("jar" in p for p in result.problems)
    with pytest.raises(ServerError):
        await server.start()


async def test_console_buffer_is_bounded(config):
    bus = EventBus()
    server = MinecraftServer(config, bus)
    for i in range(3000):
        server.console.append(f"[10:00:00] [Server thread/INFO]: line {i}")
    assert len(server.console) == 2000
    assert len(server.console.tail(100)) == 100
    assert server.console.tail(100)[-1].raw.endswith("line 2999")
    assert len(server.console.search("line 2999")) == 1
