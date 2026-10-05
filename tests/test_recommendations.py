"""The Recommendations card's rules, each checked against fake measured data,
plus dismissing and snoozing. No rule may fire from an unknown value."""

import pytest

from agent import recommendations as rec
from agent.minecraft.java import memory_limit_mb

from .conftest import PASSWORD

NOW = 1_800_000_000.0
DAY = 86400.0


def facts(**overrides) -> rec.Facts:
    """A healthy server: a fresh checked backup, a backup schedule, nothing
    measured that would worry anyone."""
    base = dict(
        now=NOW,
        backups=[{"id": 7, "name": "daily-1", "created_at": NOW - 3600, "status": "ok"}],
        schedules=[{"task": "backup", "enabled": 1}],
        samples=[],
        sample_interval=60.0,
        memory_limit_mb=4096,
        disk_free_gb=120.0,
        disk_alert_gb=5.0,
        tps_alert=15.0,
        mod_updates=[],
        java={
            "verdict": "compatible",
            "java_major": 21,
            "required": 21,
            "minecraft_version": "1.21.1",
        },
        auto_restart=True,
    )
    base.update(overrides)
    return rec.Facts(**base)


def ids(f: rec.Facts) -> list[str]:
    return [r.id for r in rec.evaluate(f)]


def samples(n, **values):
    return [{"ts": NOW - 3600 + i * 60, **values} for i in range(n)]


def test_a_healthy_server_has_no_recommendations():
    assert ids(facts()) == []


def test_every_recommendation_has_evidence_and_a_way_to_the_fix():
    f = facts(
        backups=[],
        schedules=[],
        disk_free_gb=1.0,
        auto_restart=False,
        mod_updates=[{"mod_id": "lithium", "name": "Lithium"}],
        java={
            "verdict": "incompatible",
            "java_major": 17,
            "required": 21,
            "minecraft_version": "1.21.1",
        },
        samples=samples(60, proc_ram_mb=4000, players=3, tps=9.0),
        crashes=[oom(1)],
    )
    found = rec.evaluate(f)
    assert len(found) == len(rec.RULES)
    for r in found:
        assert r.title and r.reason and r.evidence and r.fingerprint
        assert r.action.get("page") or r.action.get("url", "").startswith("https://")


# ------------------------------------------------------------------ backups
def test_no_backup_at_all():
    found = rec.evaluate(facts(backups=[]))
    assert [r.id for r in found] == ["no_backup"]
    assert "No checked backup" in found[0].evidence


def test_an_unverified_backup_does_not_count():
    f = facts(backups=[{"id": 1, "name": "x", "created_at": NOW, "status": "unverified"}])
    assert ids(f) == ["no_backup"]


def test_a_backup_older_than_a_week():
    old = [{"id": 3, "name": "daily-3", "created_at": NOW - 9 * DAY, "status": "ok"}]
    found = rec.evaluate(facts(backups=old))
    assert [r.id for r in found] == ["old_backup"]
    assert "9 days ago" in found[0].evidence


def test_no_backup_schedule():
    assert ids(facts(schedules=[{"task": "backup", "enabled": 0}])) == ["no_backup_schedule"]
    assert ids(facts(schedules=[{"task": "restart", "enabled": 1}])) == ["no_backup_schedule"]


# ------------------------------------------------------------------ memory
def oom(days_ago, crash_id=1, category="OutOfMemoryError"):
    return {"id": crash_id, "ts": NOW - days_ago * DAY, "category": category}


def test_an_out_of_memory_crash_recommends_more_memory():
    found = rec.evaluate(facts(crashes=[oom(0.5, 2), oom(3, 1)]))
    assert [r.id for r in found] == ["memory_ran_out"]
    assert "2 times in the last 7 days, last under a day ago" in found[0].evidence
    assert "4 GB" in found[0].evidence


def test_memory_use_near_the_limit_alone_is_not_a_recommendation():
    # Java's own overhead comes on top of -Xmx, so process memory at or
    # above the limit is normal for a healthy server.
    assert ids(facts(samples=samples(60, proc_ram_mb=4600))) == []


def test_old_or_other_crashes_do_not_count():
    assert ids(facts(crashes=[oom(8)])) == []
    assert ids(facts(crashes=[oom(1, category="MixinError")])) == []


def test_a_new_out_of_memory_crash_ends_a_snooze():
    db = FakeDb()
    rec.act(db, rec.evaluate(facts(crashes=[oom(2, 1)])), "memory_ran_out", "snooze")
    assert rec.visible(db, rec.evaluate(facts(crashes=[oom(2, 1)])))["recommendations"] == []
    shown = rec.visible(db, rec.evaluate(facts(crashes=[oom(0.1, 2), oom(2, 1)])))
    assert [r["id"] for r in shown["recommendations"]] == ["memory_ran_out"]


# ------------------------------------------------------------------ speed
def test_slow_while_several_players_are_on():
    f = facts(samples=samples(30, players=4, tps=19.9) + samples(15, players=4, tps=11.0))
    found = rec.evaluate(f)
    assert [r.id for r in found] == ["slow_while_busy"]
    assert "lowest 11.0" in found[0].evidence


def test_slow_with_nobody_on_is_not_a_recommendation():
    assert ids(facts(samples=samples(60, players=0, tps=5.0))) == []


@pytest.mark.parametrize("unknown", [{"players": None, "tps": 5.0}, {"players": 5, "tps": None}])
def test_speed_is_never_judged_from_unknown_values(unknown):
    assert ids(facts(samples=samples(60, **unknown))) == []


# ------------------------------------------------------------------ the rest
def test_disk_space_low_and_unknown():
    found = rec.evaluate(facts(disk_free_gb=2.5))
    assert [r.id for r in found] == ["disk_low"]
    assert "2.5 GB free" in found[0].evidence
    assert ids(facts(disk_free_gb=None)) == []


def test_mods_with_updates():
    updates = [{"mod_id": f"m{i}", "name": f"Mod {i}"} for i in range(5)]
    found = rec.evaluate(facts(mod_updates=updates))
    assert found[0].title == "Update 5 mods"
    assert "Mod 0, Mod 1, Mod 2 and 2 more" in found[0].evidence


def test_java_too_old_only_when_both_versions_are_known():
    old = {
        "verdict": "incompatible",
        "java_major": 17,
        "required": 21,
        "minecraft_version": "1.21.1",
    }
    found = rec.evaluate(facts(java=old))
    assert [r.id for r in found] == ["java_too_old"]
    assert "needs Java 21" in found[0].evidence and "Java 17" in found[0].evidence
    unknown = {"verdict": "unknown", "java_major": 17, "required": None, "minecraft_version": None}
    assert ids(facts(java=unknown)) == []
    assert ids(facts(java=None)) == []


def test_automatic_restart_turned_off():
    assert ids(facts(auto_restart=False)) == ["auto_restart_off"]


@pytest.mark.parametrize(
    ("args", "mb"),
    [(["-Xmx6G"], 6144), (["-Xms1G", "-Xmx2048M"], 2048), (["-Xmx512m"], 512), ([], None)],
)
def test_memory_limit_is_read_from_the_launch_arguments(args, mb):
    assert memory_limit_mb(args) == mb


# ------------------------------------------------------------------ dismiss and snooze
class FakeDb:
    def __init__(self):
        self.store = {}

    def get_setting(self, key, default=None):
        return self.store.get(key, default)

    def set_setting(self, key, value):
        self.store[key] = value


def test_dismissed_stays_hidden_until_restored():
    db, found = FakeDb(), rec.evaluate(facts(auto_restart=False))
    rec.act(db, found, "auto_restart_off", "dismiss")
    view = rec.visible(db, found)
    assert view["recommendations"] == []
    assert view["hidden"][0]["dismissed"] is True
    rec.act(db, found, "auto_restart_off", "restore")
    assert [r["id"] for r in rec.visible(db, found)["recommendations"]] == ["auto_restart_off"]


def test_snoozed_comes_back_when_the_evidence_changes():
    db = FakeDb()
    old = [{"id": 3, "name": "a", "created_at": NOW - 9 * DAY, "status": "ok"}]
    found = rec.evaluate(facts(backups=old))
    rec.act(db, found, "old_backup", "snooze")
    assert rec.visible(db, found)["recommendations"] == []
    # the same evidence a day later: still snoozed
    later = rec.evaluate(facts(backups=old, now=NOW + DAY))
    assert rec.visible(db, later)["recommendations"] == []
    # different evidence: back
    older = [{"id": 2, "name": "b", "created_at": NOW - 20 * DAY, "status": "ok"}]
    changed = rec.evaluate(facts(backups=older))
    assert [r["id"] for r in rec.visible(db, changed)["recommendations"]] == ["old_backup"]


def test_a_snooze_ends_when_the_problem_goes_away():
    db = FakeDb()
    found = rec.evaluate(facts(auto_restart=False))
    rec.act(db, found, "auto_restart_off", "snooze")
    rec.visible(db, rec.evaluate(facts()))  # fixed
    again = rec.evaluate(facts(auto_restart=False))  # and broken again later
    assert [r["id"] for r in rec.visible(db, again)["recommendations"]] == ["auto_restart_off"]


def test_acting_on_a_recommendation_that_no_longer_applies():
    with pytest.raises(LookupError):
        rec.act(FakeDb(), [], "disk_low", "snooze")


# ------------------------------------------------------------------ API
def test_the_api_lists_and_dismisses(client):
    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    data = client.get("/api/servers/test/recommendations").json()
    found = {r["id"] for r in data["recommendations"]}
    assert "no_backup" in found  # a fresh test server has never been backed up
    assert all(r["evidence"] for r in data["recommendations"])
    after = client.post("/api/servers/test/recommendations/no_backup", json={"action": "dismiss"})
    assert after.status_code == 200
    assert "no_backup" not in {r["id"] for r in after.json()["recommendations"]}
    assert (
        client.post(
            "/api/servers/test/recommendations/no_backup", json={"action": "explode"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/servers/test/recommendations/java_too_old", json={"action": "snooze"}
        ).status_code
        == 404
    )
