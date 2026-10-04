"""Database integrity under concurrent load, and WebSocket reconnection."""

import asyncio
import sqlite3
import threading

import pytest

from agent.database.db import Database
from agent.events import Event, EventBus
from agent.minecraft.process import MinecraftServer

from .conftest import PASSWORD


# ---------------------------------------------------------------- database
def test_schema_migrations_are_idempotent(config):
    db = Database(config.database_path)
    first = db.version
    assert db.migrate() == first
    assert db.migrate() == first
    db.close()
    reopened = Database(config.database_path)
    assert reopened.version == first
    reopened.close()


def test_a_failed_migration_leaves_no_half_applied_schema(config, monkeypatch):
    from agent.database import db as db_module

    db = Database(config.database_path)
    version = db.version
    db.close()
    broken = (
        version + 1,
        """
        CREATE TABLE half_done (id INTEGER);
        CREATE TABLE half_done (id INTEGER);
    """,
    )
    monkeypatch.setattr(db_module, "MIGRATIONS", [*db_module.MIGRATIONS, broken])
    with pytest.raises(sqlite3.Error):
        Database(config.database_path)

    conn = sqlite3.connect(str(config.database_path))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        recorded = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    finally:
        conn.close()
    assert "half_done" not in tables
    assert recorded == version


def test_wal_mode_is_active(config):
    db = Database(config.database_path)
    mode = db.query_one("PRAGMA journal_mode")
    assert str(list(mode.values())[0]).lower() == "wal"
    db.close()


def test_concurrent_writers_do_not_corrupt_the_database(config):
    """Many threads writing at once - the pattern during a crash storm, when
    events, metrics and player rows all land together."""
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    errors = []

    def writer(index: int):
        try:
            for n in range(40):
                db.add_event("test", "load_test", f"writer {index} row {n}")
                db.insert(
                    "metrics",
                    {"server_id": "test", "ts": float(n), "cpu_percent": 1.0, "players": None},
                )
        except Exception as exc:  # pragma: no cover
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert db.query_one("SELECT COUNT(*) AS n FROM events WHERE type = 'load_test'")["n"] == 320
    assert db.query_one("SELECT COUNT(*) AS n FROM metrics")["n"] == 320
    integrity = db.query_one("PRAGMA integrity_check")
    assert list(integrity.values())[0] == "ok"
    db.close()


def test_database_survives_reopening_after_an_abrupt_close(config):
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    for n in range(50):
        db.add_event("test", "before_restart", f"row {n}")
    db._conn.close()  # simulate the process disappearing without a clean stop

    reopened = Database(config.database_path)
    assert (
        reopened.query_one("SELECT COUNT(*) AS n FROM events WHERE type = 'before_restart'")["n"]
        == 50
    )
    assert list(reopened.query_one("PRAGMA integrity_check").values())[0] == "ok"
    reopened.close()


async def test_events_during_a_crash_are_all_recorded(config):
    """A crash fires several events at once; none may be lost or duplicated."""
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    bus = EventBus()
    bus.subscribe(lambda event: db.add_event("test", event.type, event.message, level=event.level))
    await asyncio.gather(
        *[
            bus.publish(Event(type="server_crashed", message=f"crash {i}", level="error"))
            for i in range(25)
        ]
    )
    assert db.query_one("SELECT COUNT(*) AS n FROM events WHERE type = 'server_crashed'")["n"] == 25
    db.close()


def test_metrics_pruning_bounds_growth(config):
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    import time

    old = time.time() - 40 * 86400
    for n in range(100):
        db.insert("metrics", {"server_id": "test", "ts": old + n, "cpu_percent": 1.0})
    for _ in range(10):
        db.insert("metrics", {"server_id": "test", "ts": time.time(), "cpu_percent": 1.0})
    db.prune(metrics_days=14)
    assert db.query_one("SELECT COUNT(*) AS n FROM metrics")["n"] == 10
    db.close()


def test_console_buffer_never_grows_without_bound(config):
    """Large logs must not be held in memory or pushed wholesale to clients."""
    bus = EventBus()
    server = MinecraftServer(config, bus)
    for n in range(50_000):
        server.console.append(f"[10:00:00] [Server thread/INFO]: line {n}")
    assert len(server.console) == 2000
    assert len(server.console.tail(10_000)) == 2000, "tail is capped by the buffer"
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    assert db.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 0, (
        "console lines must not be written to the database"
    )
    db.close()


# ---------------------------------------------------------------- websocket
def token_for(client):
    return client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "token"
    ]


def test_websocket_can_reconnect_after_a_drop(client):
    """A dropped socket must not leave the agent holding the old subscriber."""
    token = token_for(client)
    core = client.app.state.core
    before = core.bus.subscriber_count

    for _ in range(3):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": token})
            assert ws.receive_json()["type"] == "ready"
        # after the context exits the connection is closed

    for _ in range(50):
        if core.bus.subscriber_count == before:
            break
        import time

        time.sleep(0.05)
    assert core.bus.subscriber_count == before, "queues leaked after disconnects"

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready", "reconnection still works"


def test_revoked_token_cannot_reconnect(client):
    token = token_for(client)
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "error"


def test_websocket_cannot_perform_actions(client):
    """The socket is read-only: control belongs on the audited REST API."""
    token = token_for(client)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        ws.send_json({"type": "command", "command": "stop", "confirm": True})
        ws.send_json({"type": "status"})
        # the command is ignored; the next reply is the status we asked for
        reply = ws.receive_json()
        assert reply["type"] == "status"
        assert reply["status"]["state"] != "STOPPING"


def test_live_events_arrive_in_a_shape_the_dashboard_recognises(client):
    """Regression: events were sent as {"type": "event", **event}, so the
    event's own type overwrote "event" and the browser dropped every one."""
    token = token_for(client)
    core = client.app.state.core
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        client.portal.call(
            core.bus.publish,
            Event(type="console", message="[10:00:00] hello", data={"raw": "[10:00:00] hello"}),
        )
        message = ws.receive_json()
        assert message["type"] == "event"
        assert message["event"]["type"] == "console"
        assert message["event"]["message"] == "[10:00:00] hello"


async def test_fire_and_forget_publishes_are_kept_until_they_run():
    import gc

    bus = EventBus()
    seen = []
    bus.subscribe(lambda event: seen.append(event.type))
    bus.publish_soon(Event(type="ping"))
    assert len(bus._pending) == 1
    gc.collect()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert seen == ["ping"]
    assert not bus._pending
