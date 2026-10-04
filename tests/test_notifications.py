import asyncio

import httpx
import pytest

from agent.database.db import Database
from agent.events import Event, EventBus
from agent.minecraft.process import MinecraftServer
from agent.monitoring.metrics import MetricsMonitor
from agent.monitoring.players import PlayerTracker
from agent.notifications.dispatcher import Notifier


@pytest.fixture
def parts(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return config, bus, db, server


# ---------------------------------------------------------------- notifications
async def test_a_failing_webhook_never_raises(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")

    async def explode(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.AsyncClient, "post", explode)
    notifier = Notifier(config, bus, db, server)

    await notifier.handle(Event(type="server_crashed", message="boom", level="error"))
    await notifier.drain()

    history = notifier.history()
    assert history[0]["status"] == "failed"
    assert history[0]["channel"] == "discord"


async def test_failure_is_published_as_an_event(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    seen = []
    bus.subscribe(lambda event: seen.append(event.type))

    async def explode(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx.AsyncClient, "post", explode)
    notifier = Notifier(config, bus, db, server)
    await notifier.handle(Event(type="server_crashed", message="boom"))
    await notifier.drain()
    assert "notification_failed" in seen


async def test_missing_webhook_is_skipped_not_failed(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.delenv("MCSC_DISCORD_WEBHOOK", raising=False)
    notifier = Notifier(config, bus, db, server)
    await notifier.handle(Event(type="server_started", message="up"))
    await notifier.drain()
    assert notifier.history()[0]["status"] == "skipped"


async def test_disabled_events_are_not_sent(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    config.set("notifications.events.player_left", False)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    notifier = Notifier(config, bus, db, server)
    await notifier.handle(Event(type="player_left", message="Steve left"))
    await notifier.drain()
    assert notifier.history() == []


async def test_repeat_alerts_are_throttled(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    config.set("notifications.min_interval_seconds", 600)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    sent = []

    async def fake_post(self, url, **kwargs):
        sent.append(url)
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    notifier = Notifier(config, bus, db, server)
    for _ in range(4):
        await notifier.handle(Event(type="high_ram", message="RAM at 95%"))
    await notifier.drain()
    assert len(sent) == 1


async def test_crash_notification_carries_the_analysis(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    captured = {}

    async def fake_post(self, url, **kwargs):
        captured.update(kwargs.get("json") or {})
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    notifier = Notifier(config, bus, db, server)
    await notifier.handle(
        Event(
            type="server_crashed",
            message="Server crashed",
            level="error",
            data={
                "exit_code": 1,
                "analysis": {
                    "category": "OutOfMemoryError",
                    "confidence": "likely",
                    "summary": "Ran out of heap",
                    "evidence": ["java.lang.OutOfMemoryError"],
                },
            },
        )
    )
    await notifier.drain()
    fields = captured["embeds"][0]["fields"]
    names = " ".join(f["name"] for f in fields)
    assert "Likely cause" in names
    assert "Evidence" in names


async def test_a_slow_alert_never_stalls_the_console(parts, monkeypatch):
    """A Discord send that hangs must not stop console lines from flowing."""
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    release = asyncio.Event()

    async def hang(self, url, **kwargs):
        await release.wait()
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", hang)
    notifier = Notifier(config, bus, db, server)
    bus.subscribe(notifier.handle)
    seen = []
    queue = bus.queue()

    # Start the real fake server: its startup line publishes server_started,
    # which triggers the hanging Discord send, while the console keeps going.
    await server.start()
    try:
        assert await server.wait_online(10)
        await asyncio.wait_for(server.send_command("list"), 5)
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            try:
                event = await asyncio.wait_for(queue.get(), 0.5)
            except asyncio.TimeoutError:
                continue
            if event.type == "console":
                seen.append(event.message)
                if any("players online" in line for line in seen):
                    break
        assert any("players online" in line for line in seen), seen
        assert not release.is_set()
    finally:
        release.set()
        await server.stop()
        await notifier.stop()


async def test_publish_returns_before_a_slow_alert_is_sent(parts, monkeypatch):
    config, bus, db, server = parts
    config.set("notifications.discord_enabled", True)
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.example/webhook")
    release = asyncio.Event()
    sent = []

    async def hang(self, url, **kwargs):
        await release.wait()
        sent.append(url)
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", hang)
    notifier = Notifier(config, bus, db, server)
    bus.subscribe(notifier.handle)
    await asyncio.wait_for(bus.publish(Event(type="server_crashed", message="boom")), 1)
    assert sent == []
    release.set()
    await notifier.drain()
    assert len(sent) == 1
    await notifier.stop()


# ---------------------------------------------------------------- health honesty
def test_health_reports_unknown_tps_rather_than_guessing(parts):
    config, bus, db, server = parts
    metrics = MetricsMonitor(config, bus, db, server)
    health = metrics.health(player_count=0)
    tps = next(c for c in health["checks"] if c["name"] == "TPS")
    assert tps["status"] == "unknown"
    assert tps["value"] is None
    assert "tick" in tps["detail"].lower()


def test_health_checks_expose_value_and_threshold(parts):
    config, bus, db, server = parts
    metrics = MetricsMonitor(config, bus, db, server)
    for check in metrics.health()["checks"]:
        assert "value" in check and "detail" in check
        assert check["status"] in ("ok", "warn", "unknown")


async def test_threshold_breach_publishes_a_warning(parts):
    config, bus, db, server = parts
    config.set("thresholds.cpu_percent", 0.0)
    config.set("thresholds.disk_free_gb", 10_000_000.0)
    seen = []
    bus.subscribe(lambda event: seen.append(event.type))
    metrics = MetricsMonitor(config, bus, db, server)
    await metrics.sample_once(player_count=0)
    assert "high_cpu" in seen
    assert "low_disk" in seen


async def test_metrics_samples_are_stored_and_retrievable(parts):
    config, bus, db, server = parts
    metrics = MetricsMonitor(config, bus, db, server)
    await metrics.sample_once(player_count=3)
    await metrics.sample_once(player_count=4)
    history = metrics.history(hours=1)
    assert len(history) == 2
    assert history[-1]["players"] == 4
    assert history[-1]["ram_total_mb"] > 0


# ---------------------------------------------------------------- players
async def test_player_join_and_leave_accumulates_playtime(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    await tracker.player_joined("Steve")
    assert [p["username"] for p in tracker.online()] == ["Steve"]
    await asyncio.sleep(0.05)
    await tracker.player_left("Steve")
    assert tracker.online() == []
    known = tracker.all_players()[0]
    assert known["sessions"] == 1
    assert known["total_seconds"] > 0
    assert tracker.sessions("Steve")[0]["left_at"] is not None


async def test_uuid_is_captured_from_the_console_line(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    server.signal_hook = tracker.handle_signals
    from agent.minecraft.console import parse_line
    from agent.minecraft.console import extract_signals

    uuid_line = parse_line(
        "[10:00:00] [User Authenticator #1/INFO]: UUID of player Steve is "
        "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        1,
    )
    join_line = parse_line("[10:00:01] [Server thread/INFO]: Steve joined the game", 2)
    await tracker.handle_signals(extract_signals(uuid_line), uuid_line)
    await tracker.handle_signals(extract_signals(join_line), join_line)
    assert tracker.online()[0]["uuid"] == "069a79f4-44e9-4726-a5be-fca90e38aaf5"


async def test_stopping_the_server_clears_the_online_list(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    await tracker.player_joined("Steve")
    await tracker.player_joined("Alex")
    await tracker.clear_online()
    assert tracker.online() == []


async def test_player_list_reply_reconciles_state(parts):
    config, bus, db, server = parts
    tracker = PlayerTracker(config, bus, db, "test")
    await tracker.player_joined("Ghost")
    await tracker.reconcile(["Steve", "Alex"])
    assert sorted(p["username"] for p in tracker.online()) == ["Alex", "Steve"]
