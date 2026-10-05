"""The shared building blocks: jobs, the safe-change routine, the port
manager, permissions and per-server alerts."""

import asyncio

import pytest
from fastapi.routing import APIRoute

from agent.core import AgentCore
from agent.database.db import Database
from agent.events import Event, EventBus
from agent.jobs import JobConflict, JobTracker
from agent.notifications.dispatcher import Notifier
from agent.ports import game_port, read_properties_port
from agent.safechange import SafeChange, SafeChangeError, run_safe_change
from agent.security import permissions

from .conftest import build_multi_config


@pytest.fixture
def tracker(config):
    db = Database(config.database_path)
    yield JobTracker(db, EventBus())
    db.close()


@pytest.fixture
async def core(tmp_path):
    core = AgentCore(build_multi_config(tmp_path))
    yield core
    await core.jobs.stop()
    core.db.close()


# ------------------------------------------------------------------ jobs
async def test_progress_is_unknown_until_the_total_is_known(tracker):
    seen = []

    async def work(job):
        job.step("Counting")
        seen.append(tracker.get(job.id).progress)
        job.step("Copying", total=4, unit="files")
        job.advance(1)
        seen.append(tracker.get(job.id).progress)
        return {"copied": 4}

    job, result = await tracker.run("test", "Copy things", work, server_id="a")
    assert seen == [None, 0.25]  # never a made-up percentage
    assert result == {"copied": 4}
    stored = tracker.get(job.id)
    assert stored.state == "succeeded"
    assert stored.result == {"copied": 4}


async def test_one_risky_job_per_server(tracker):
    gate = asyncio.Event()

    async def slow(job):
        await gate.wait()

    running = tracker.start("restore", "Restore world", slow, server_id="a", risky=True)
    await asyncio.sleep(0)
    with pytest.raises(JobConflict) as info:
        await tracker.run("restore", "Another", slow, server_id="a", risky=True)
    assert "Restore world" in str(info.value)
    # Another server is not held up.
    gate.set()
    await tracker.run("restore", "Other server", slow, server_id="b", risky=True)
    for _ in range(50):
        if tracker.get(running.id).state != "running":
            break
        await asyncio.sleep(0.01)
    assert tracker.get(running.id).state == "succeeded"


async def test_a_failed_job_records_why(tracker):
    async def broken(job):
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        await tracker.run("backup", "Back up", broken, server_id="a")
    (job,) = tracker.recent("a")
    assert job.state == "failed"
    assert job.message == "disk full"


async def test_jobs_left_running_are_marked_interrupted_at_startup(tracker):
    gate = asyncio.Event()

    async def slow(job):
        await gate.wait()

    job = tracker.start("backup", "Back up", slow, server_id="a")
    await asyncio.sleep(0)
    fresh = JobTracker(tracker.db, EventBus())  # as if the agent restarted
    assert fresh.mark_interrupted() == 1
    assert fresh.get(job.id).state == "interrupted"
    gate.set()
    await tracker.stop()


# ------------------------------------------------------------------ safe change
async def test_a_safe_change_takes_a_backup_first_and_can_be_undone(core):
    ctx = core.get_server("survival")
    props = ctx.config.server_dir / "server.properties"
    before = props.read_text()

    async def change(job):
        props.write_text("server-port=25599\n")
        return {"changed": "server.properties"}

    result = await run_safe_change(
        ctx.server, ctx.backups, SafeChange(title="Change the port", change=change)
    )
    assert result["safety_backup"]["verified"] is True
    assert result["undo"]["kind"] == "restore_backup"
    assert props.read_text() == "server-port=25599\n"
    await ctx.backups.restore(result["undo"]["backup_id"], user="tester")
    assert props.read_text() == before


async def test_a_failed_check_puts_the_files_back(core):
    ctx = core.get_server("survival")
    props = ctx.config.server_dir / "server.properties"
    before = props.read_text()

    async def change(job):
        props.write_text("broken\n")
        return {}

    async def check(result):
        return False, "server.properties has no port"

    with pytest.raises(SafeChangeError) as info:
        await run_safe_change(
            ctx.server, ctx.backups, SafeChange(title="Break it", change=change, check=check)
        )
    assert "put back" in str(info.value)
    assert props.read_text() == before


async def test_a_change_that_raises_puts_the_files_back(core):
    ctx = core.get_server("creative")
    level = ctx.config.server_dir / "world" / "level.dat"
    before = level.read_bytes()

    async def change(job):
        level.write_bytes(b"half written")
        raise OSError("disk full")

    with pytest.raises(SafeChangeError):
        await run_safe_change(ctx.server, ctx.backups, SafeChange(title="Fail", change=change))
    assert level.read_bytes() == before


async def test_the_server_cannot_start_while_a_change_holds_it(core):
    from agent.minecraft.process import ServerError

    ctx = core.get_server("survival")
    refused = []

    async def change(job):
        # A click on Start, a schedule or another device, mid-change.
        with pytest.raises(ServerError) as info:
            await ctx.server.start(actor="someone")
        refused.append(str(info.value))
        return {}

    await run_safe_change(ctx.server, ctx.backups, SafeChange(title="Restoring x", change=change))
    assert refused and "Restoring x" in refused[0]
    assert ctx.server.held_by is None  # released afterwards
    assert not any("Restoring" in p for p in ctx.server.preflight().problems)


async def test_a_failed_change_releases_the_server(core):
    ctx = core.get_server("survival")

    async def change(job):
        raise OSError("disk full")

    with pytest.raises(SafeChangeError):
        await run_safe_change(ctx.server, ctx.backups, SafeChange(title="Fail", change=change))
    assert ctx.server.held_by is None


async def test_a_backup_is_a_job_with_real_progress(core):
    ctx = core.get_server("creative")
    seen = []
    core.bus.subscribe(lambda e: seen.append(e) if e.type == "job" else None)
    result = await ctx.backups.create(name="manual", user="tester")
    job = core.jobs.get(result["job_id"])
    assert job.state == "succeeded"
    assert job.server_id == "creative"
    writing = [e.data for e in seen if e.data.get("step") == "Writing the backup"]
    assert writing and all(d["total"] and d["done"] <= d["total"] for d in writing)
    assert all(e.server_id == "creative" for e in seen)


async def test_undo_through_the_jobs_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    from .conftest import PASSWORD

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    config = build_multi_config(tmp_path)
    props = config.for_server("creative").server_dir / "server.properties"
    with TestClient(create_app(config)) as client:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        backup = client.post("/api/servers/creative/backups", json={"name": "before"}).json()
        props.write_text("server-port=1\n")
        restored = client.post(
            f"/api/servers/creative/backups/{backup['id']}/restore", json={"confirm": True}
        )
        assert restored.status_code == 200, restored.text
        assert "server-port=25566" in props.read_text()
        job_id = restored.json()["job_id"]
        listed = client.get("/api/jobs", params={"server_id": "creative"}).json()["jobs"]
        assert job_id in [j["id"] for j in listed]
        undone = client.post(f"/api/jobs/{job_id}/undo")
        assert undone.status_code == 200, undone.text
        assert props.read_text() == "server-port=1\n"
        assert client.get("/api/jobs", params={"server_id": "nope"}).status_code == 404


# ------------------------------------------------------------------ ports
def test_the_port_comes_from_server_properties(tmp_path):
    (tmp_path / "server.properties").write_text("motd=x\nserver-port=25570\n")
    assert read_properties_port(tmp_path) == 25570
    assert game_port(tmp_path).port == 25570
    assert game_port(tmp_path, detected=25571).source == "server console"


def test_a_missing_port_is_minecrafts_default_and_says_so(tmp_path):
    port = game_port(tmp_path)
    assert port.port == 25565
    assert "default" in port.source


async def test_port_suggestions_skip_ports_servers_use(core):
    used = core.ports.used()
    assert used[("tcp", 25565)] == "survival"
    assert used[("tcp", 25566)] == "creative"
    suggestion = core.ports.suggest()
    assert suggestion not in (25565, 25566)


# ------------------------------------------------------------------ permissions
def test_every_route_declares_its_permission():
    from agent.api.routes import router

    public = {"/api/health", "/api/auth/login"}
    missing = []
    for route in router.routes:
        if not isinstance(route, APIRoute) or route.path in public:
            continue
        declared = [
            dep.call.permission
            for dep in route.dependant.dependencies
            if hasattr(dep.call, "permission")
        ]
        if not declared or declared[0] not in permissions.ALL:
            missing.append(f"{sorted(route.methods)} {route.path}")
    assert not missing, missing


def test_websocket_actions_declare_permissions():
    assert set(permissions.WS_ACTIONS.values()) <= permissions.ALL


# ------------------------------------------------------------------ alerts
async def test_alerts_name_the_server(core):
    ctx = core.get_server("creative")
    event = Event(type="server_crashed", message="boom", level="error", server_id="creative")
    emoji, colour, title = core.notifier.title(event)
    assert title == f"{ctx.name} crashed"


async def test_the_alert_cooldown_is_per_server(core, monkeypatch):
    sent = []

    async def deliver(event):
        sent.append(event.server_id)

    monkeypatch.setattr(core.notifier, "deliver", deliver)
    notifier: Notifier = core.notifier
    for server_id in ("survival", "creative", "survival"):
        await notifier.handle(Event(type="high_cpu", message="hot", server_id=server_id))
    await notifier.drain()
    assert sent == ["survival", "creative"]  # the second Survival alert is held back


async def test_two_backups_in_the_same_second_do_not_overwrite_each_other(core):
    ctx = core.get_server("creative")
    first = await ctx.backups.create(name="same", user="tester")
    second = await ctx.backups.create(name="same", user="tester")
    assert first["name"] != second["name"]
    assert ctx.backups.verify(first["id"])["ok"]
    assert ctx.backups.verify(second["id"])["ok"]


async def test_mod_changes_wait_for_a_change_that_holds_the_server(core):
    ctx = core.get_server("survival")
    ctx.server.held_by = "Restoring x"
    try:
        with pytest.raises(JobConflict) as info:
            await ctx.mod_change("Removing a.jar", lambda: asyncio.sleep(0))
        assert "Restoring x" in str(info.value)
    finally:
        ctx.server.held_by = None


async def test_a_restore_waits_for_a_mod_change(core):
    ctx = core.get_server("survival")
    gate = asyncio.Event()

    async def slow_change():
        await gate.wait()
        return {"ok": True}

    task = asyncio.create_task(ctx.mod_change("Installing sodium", slow_change))
    await asyncio.sleep(0.05)
    with pytest.raises(JobConflict) as info:
        await ctx.backups.create(kind="manual")
    assert "Installing sodium" in str(info.value)
    gate.set()
    assert await task == {"ok": True}


async def test_a_filtered_queue_never_loses_a_crash_to_another_servers_console():
    from agent.api.ws import PAGE_ONLY

    bus = EventBus()
    watching = "creative"
    q = bus.queue(
        maxsize=5,
        accept=lambda e: e.type not in PAGE_ONLY or e.server_id in (None, watching),
    )
    await bus.publish(Event(type="server_crashed", message="boom", server_id="survival"))
    for _ in range(50):  # a busy console on the server nobody is looking at
        await bus.publish(Event(type="console", message="spam", server_id="survival"))
    await bus.publish(Event(type="console", message="mine", server_id="creative"))
    received = [q.get_nowait() for _ in range(q.qsize())]
    assert [e.type for e in received] == ["server_crashed", "console"]
    assert received[1].server_id == "creative"
