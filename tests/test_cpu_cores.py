"""Limiting which CPU cores each server may use, and measuring CPU honestly
when several servers sample it."""

import pytest

from agent.config import ConfigError
from agent.events import EventBus
from agent.minecraft import cpu
from agent.minecraft.process import MinecraftServer, ServerError
from agent.monitoring import metrics as metrics_module
from agent.monitoring.metrics import MetricsMonitor

from .conftest import build_config
from .test_api import auth, token_for

needs_affinity = pytest.mark.skipif(
    not cpu.supported()[0], reason="this operating system cannot set a process's cores"
)


def test_cores_are_described_the_way_people_count_them():
    assert cpu.describe([0, 1, 2, 3, 6]) == "1-4, 7"
    assert cpu.describe([5]) == "6"
    assert cpu.describe([]) == "none"


def test_java_is_told_how_many_cores_it_has():
    assert cpu.jvm_args([0, 1], ["-Xmx4G"]) == ["-XX:ActiveProcessorCount=2"]
    assert cpu.jvm_args([], ["-Xmx4G"]) == []
    # The owner's own flag wins.
    assert cpu.jvm_args([0, 1], ["-XX:ActiveProcessorCount=8"]) == []


def test_the_launch_command_carries_the_core_count(tmp_path):
    cfg = build_config(tmp_path, **{"server.raw_command": None, "server.cpu_cores": [0]})
    command = MinecraftServer(cfg, EventBus()).build_command()
    assert "-XX:ActiveProcessorCount=1" in command
    assert command.index("-XX:ActiveProcessorCount=1") < command.index("-jar")


@pytest.mark.parametrize("bad", [["a"], [-1], [1, 1], "0-3", [True]])
def test_a_nonsense_core_list_stops_startup(tmp_path, bad):
    with pytest.raises(ConfigError):
        build_config(tmp_path, **{"server.cpu_cores": bad}).validate()


def test_cores_this_pc_does_not_have_block_the_start(tmp_path):
    count = cpu.logical_cores()
    cfg = build_config(tmp_path, **{"server.cpu_cores": [0, count + 3]})
    pre = MinecraftServer(cfg, EventBus()).preflight()
    assert not pre.ok
    assert f"This PC has {count} cores" in " ".join(pre.problems)


@needs_affinity
async def test_the_running_server_uses_only_its_cores(tmp_path):
    cfg = build_config(tmp_path, **{"server.cpu_cores": [0]})
    server = MinecraftServer(cfg, EventBus())
    try:
        await server.start()
        status = server.status()["cpu_cores"]
        assert status["configured"] == [0]
        assert status["applied"] == [0]  # read back from the process itself
    finally:
        await server.stop()


@needs_affinity
async def test_a_change_applies_to_the_running_server(tmp_path):
    cfg = build_config(tmp_path)
    server = MinecraftServer(cfg, EventBus())
    try:
        await server.start()
        everything = server.status()["cpu_cores"]["applied"]
        assert everything is not None and len(everything) == cpu.logical_cores()
        cfg.set("server.cpu_cores", [0])
        result = await server.apply_cpu_cores()
        assert result["ok"] and result["applied"] == [0]
        cfg.set("server.cpu_cores", [])
        result = await server.apply_cpu_cores()
        assert result["applied"] == everything
    finally:
        await server.stop()


async def test_the_cores_of_a_stopped_server_are_unknown_not_assumed(tmp_path):
    cfg = build_config(tmp_path, **{"server.cpu_cores": [0]})
    status = MinecraftServer(cfg, EventBus()).status()["cpu_cores"]
    assert status["configured"] == [0]
    assert status["applied"] is None
    assert status["applied_reason"]


@pytest.fixture
def signed_in(client):
    client.headers.update(auth(token_for(client)))
    return client


def test_the_settings_api_refuses_cores_this_pc_does_not_have(signed_in):
    client = signed_in
    count = cpu.logical_cores()
    response = client.put(
        "/api/servers/test/settings", json={"updates": {"server.cpu_cores": [count + 1]}}
    )
    assert response.status_code == 200
    body = response.json()
    assert "server.cpu_cores" in body["rejected"]
    assert body["applied"] == {}


def test_the_settings_api_lists_the_cores(signed_in):
    client = signed_in
    data = client.get("/api/servers/test/settings").json()
    assert data["cpu"]["logical_cores"] == cpu.logical_cores()
    assert data["cpu"]["status"]["configured"] is None  # every core
    response = client.put("/api/servers/test/settings", json={"updates": {"server.cpu_cores": [0]}})
    assert response.json()["applied"] == {"server.cpu_cores": [0]}
    assert client.get("/api/servers/test/settings").json()["server"]["cpu_cores"] == [0]


# ------------------------------------------------------------------ measuring
def test_two_servers_sampling_back_to_back_see_the_same_pc_cpu(config, monkeypatch):
    """psutil measures "since the last call on this thread": the second of two
    servers sampling in a row used to read about 0%."""
    fake = iter([(10.0, 90.0), (60.0, 140.0), (60.0, 140.0), (60.0, 140.0)])

    class Times(tuple):
        @property
        def idle(self):
            return self[1]

    monkeypatch.setattr(metrics_module.psutil, "cpu_times", lambda: Times(next(fake)))
    clock = iter([100.0, 105.0, 105.001, 105.002])
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: next(clock))
    shared = metrics_module._MachineCpu()
    assert shared.percent() is None  # one reading is not a measurement
    first = shared.percent()  # 5 s later: 50 busy of 100 = 50%
    second = shared.percent()  # a millisecond later: the same reading
    assert first == 50.0
    assert second == first


def test_cpu_is_unknown_until_it_has_been_measured(config, monkeypatch):
    monkeypatch.setattr(metrics_module, "machine_cpu", metrics_module._MachineCpu())
    server = MinecraftServer(config, EventBus())
    snap = MetricsMonitor(config, EventBus(), None, server).snapshot()
    assert snap["cpu_percent"] is None
    assert snap["process_cpu_percent"] is None


def test_a_start_with_a_bad_core_list_says_why(tmp_path):
    import asyncio

    count = cpu.logical_cores()
    cfg = build_config(tmp_path, **{"server.cpu_cores": [count + 1]})
    server = MinecraftServer(cfg, EventBus())
    with pytest.raises(ServerError) as info:
        asyncio.run(server.start())
    assert "cores" in str(info.value)
