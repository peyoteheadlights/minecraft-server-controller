"""Per-account display preferences (Simple or Technical, theme), and the
graph series behind the Performance page."""

import time

from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.process import MinecraftServer
from agent.monitoring.metrics import MetricsMonitor

from .conftest import PASSWORD


def signed_in(client):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    return client


# ------------------------------------------------------------------ preferences
def test_preferences_default_to_simple_and_follow_the_system(client):
    signed_in(client)
    assert client.get("/api/account/preferences").json() == {"mode": "simple", "theme": "system"}
    assert client.get("/api/auth/me").json()["preferences"]["mode"] == "simple"


def test_preferences_are_saved_on_the_server(client):
    signed_in(client)
    saved = client.put("/api/account/preferences", json={"mode": "technical"})
    assert saved.json() == {"mode": "technical", "theme": "system"}
    client.put("/api/account/preferences", json={"theme": "graphite"})
    # A second sign-in (another device) sees the same choices.
    del client.headers["Authorization"]
    signed_in(client)
    assert client.get("/api/account/preferences").json() == {
        "mode": "technical",
        "theme": "graphite",
    }


def test_unknown_preference_values_are_refused(client):
    signed_in(client)
    assert client.put("/api/account/preferences", json={"mode": "expert"}).status_code == 422
    assert client.put("/api/account/preferences", json={"theme": "neon"}).status_code == 422
    assert client.get("/api/account/preferences").json()["mode"] == "simple"


def test_preferences_need_a_sign_in(client):
    assert client.get("/api/account/preferences").status_code == 401


# ------------------------------------------------------------------ graph series
def _metrics(config):
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, EventBus(), db)
    return db, MetricsMonitor(config, EventBus(), db, server)


def _sample(db, ts, **values):
    db.insert("metrics", {"server_id": "test", "ts": ts, **values})


def test_a_week_is_averaged_into_a_bounded_number_of_points(config):
    db, metrics = _metrics(config)
    now = time.time()
    for i in range(0, 7 * 24 * 60, 10):  # a sample every 10 minutes for a week
        _sample(db, now - i * 60, cpu_percent=50.0, tps=20.0)
    series = metrics.series(hours=168, points=200)
    assert 100 < len(series["points"]) <= 201
    assert series["bucket_seconds"] >= 168 * 3600 / 200
    assert all(p["cpu_percent"] == 50.0 for p in series["points"])


def test_unmeasured_values_stay_null_and_missing_time_stays_missing(config):
    db, metrics = _metrics(config)
    size = metrics.series(hours=1, points=360)["bucket_seconds"]
    start = (int(time.time() / size) - 50) * size  # the start of a bucket 50 buckets ago
    _sample(db, time.time() - 3500, cpu_percent=10.0, tps=None, proc_ram_mb=None)  # server off
    _sample(db, start + 0.1, cpu_percent=20.0, tps=19.5, proc_ram_mb=900.0)
    _sample(db, start + 0.2, cpu_percent=30.0, tps=18.5, proc_ram_mb=1100.0)
    series = metrics.series(hours=1, points=360)
    points = series["points"]
    # Two buckets with data; the time between them is not filled in.
    assert len(points) == 2
    assert points[0]["tps"] is None and points[0]["proc_ram_mb"] is None
    assert points[1]["tps"] == 19.0 and points[1]["tps_min"] == 18.5
    assert points[1]["proc_ram_max"] == 1100.0
    assert points[1]["ts"] - points[0]["ts"] > 10 * series["bucket_seconds"]


def test_the_performance_route_returns_the_series(client):
    signed_in(client)
    data = client.get("/api/servers/test/performance?hours=24").json()
    assert data["series"]["hours"] == 24
    assert "bucket_seconds" in data["series"]
    assert data["sample_interval"] > 0
