import asyncio
import threading

from agent.database.db import Database
from agent.database.event_writer import EventWriter


async def test_events_are_written_in_a_batch_off_the_event_loop(config, monkeypatch):
    db = Database(config.database_path)
    writer = EventWriter(db)
    threads = []
    original = db.add_events

    def spy(rows):
        threads.append((threading.current_thread(), len(rows)))
        original(rows)

    monkeypatch.setattr(db, "add_events", spy)
    for n in range(30):
        writer.add("test", "burst", f"event {n}")
    assert db.recent_events("test") == [], "publishing must not wait for the disk"
    await writer.flush()
    assert len(db.recent_events("test", limit=100)) == 30
    assert threads == [(threads[0][0], 30)]
    assert threads[0][0] is not threading.main_thread()
    await writer.stop()


async def test_the_background_task_writes_without_a_flush(config):
    db = Database(config.database_path)
    writer = EventWriter(db)
    writer.INTERVAL = 0.05
    writer.add("test", "tick", "hello", data={"n": 1})
    for _ in range(40):
        await asyncio.sleep(0.05)
        if db.recent_events("test"):
            break
    row = db.recent_events("test")[0]
    assert row["type"] == "tick" and row["data"] == '{"n": 1}'
    await writer.stop()


async def test_stop_writes_what_is_left(config):
    db = Database(config.database_path)
    writer = EventWriter(db)
    writer.add("test", "last", "goodbye")
    await writer.stop()
    assert db.recent_events("test")[0]["type"] == "last"
