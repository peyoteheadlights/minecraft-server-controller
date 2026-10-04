import asyncio
import threading

import pytest

from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.process import MinecraftServer
from agent.monitoring.metrics import MetricsMonitor

MB = 1024 * 1024


@pytest.fixture
def metrics(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    return MetricsMonitor(config, bus, db, server)


def test_backups_in_the_data_folder_are_counted_once(metrics, config):
    # The default data folder lives inside the server folder.
    config.set("paths.data_dir", str(config.server_dir / "mcsc-data"))
    config.backup_dir.mkdir(parents=True, exist_ok=True)
    (config.backup_dir / "backup.zip").write_bytes(b"x" * (3 * MB))
    (config.server_dir / "fabric-server-launch.jar").write_bytes(b"x" * MB)

    storage = metrics.storage_breakdown()

    assert storage["backups_gb"] * 1024 == pytest.approx(3, abs=0.01)
    assert storage["other_gb"] * 1024 < 1.1, "backups must not be counted again under Other"


async def test_storage_is_measured_off_the_event_loop_and_cached(metrics, monkeypatch):
    threads = []
    original = metrics.storage_breakdown

    def spy():
        threads.append(threading.current_thread())
        return original()

    monkeypatch.setattr(metrics, "storage_breakdown", spy)
    first, second = await asyncio.gather(metrics.storage(), metrics.storage())
    assert first is second
    await metrics.storage()
    assert len(threads) == 1, "concurrent and repeat callers share one cached walk"
    assert threads[0] is not threading.main_thread()
