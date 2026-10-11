"""Undo and Redo: two stacks of changes per server (agent/changes.py)."""

import pytest

from agent.changes import ChangeError
from agent.core import AgentCore
from agent.safechange import SafeChange, SafeChangeError, run_safe_change

from .conftest import build_multi_config


@pytest.fixture
async def core(tmp_path):
    core = AgentCore(build_multi_config(tmp_path))
    yield core
    await core.jobs.stop()
    core.db.close()


def props(ctx):
    return ctx.config.server_dir / "server.properties"


async def set_motd(ctx, motd, **options):
    """A change through the safe-change routine: the motd line is rewritten."""
    path = props(ctx)

    async def change(job):
        lines = [ln for ln in path.read_text().splitlines() if not ln.startswith("motd=")]
        path.write_text("\n".join([*lines, f"motd={motd}"]) + "\n")
        return {}

    return await run_safe_change(
        ctx.server,
        ctx.backups,
        SafeChange(title=f"Setting the motd to {motd}", change=change, **options),
    )


def motd(ctx):
    return next(
        (
            ln.split("=", 1)[1]
            for ln in props(ctx).read_text().splitlines()
            if ln.startswith("motd=")
        ),
        None,
    )


def titles(stack):
    return [entry["title"] for entry in stack]


async def test_undo_goes_back_one_change_at_a_time(core):
    ctx = core.get_server("survival")
    for name in ("one", "two", "three"):
        await set_motd(ctx, name)
    changes = ctx.backups.changes
    assert titles(changes.undo_stack())[0] == "Setting the motd to three"

    await changes.undo(user="tester")
    assert motd(ctx) == "two"
    await changes.undo(user="tester")
    assert motd(ctx) == "one"
    # Undo is not a change of its own, so the stacks just moved.
    assert titles(changes.undo_stack()) == ["Setting the motd to one"]
    assert titles(changes.redo_stack()) == ["Setting the motd to two", "Setting the motd to three"]


async def test_redo_puts_back_the_change_undone_last(core):
    ctx = core.get_server("survival")
    for name in ("one", "two"):
        await set_motd(ctx, name)
    changes = ctx.backups.changes
    await changes.undo(user="tester")
    await changes.undo(user="tester")
    await changes.redo(user="tester")
    assert motd(ctx) == "one"
    await changes.redo(user="tester")
    assert motd(ctx) == "two"
    assert changes.redo_stack() == []
    # And it can be undone again.
    await changes.undo(user="tester")
    assert motd(ctx) == "one"


async def test_a_new_change_empties_redo(core):
    ctx = core.get_server("survival")
    await set_motd(ctx, "one")
    await set_motd(ctx, "two")
    changes = ctx.backups.changes
    await changes.undo(user="tester")
    assert changes.redo_stack()
    await set_motd(ctx, "other")
    assert changes.redo_stack() == []
    with pytest.raises(ChangeError):
        await changes.redo(user="tester")


async def test_a_change_undo_cant_reverse_only_empties_redo(core):
    ctx = core.get_server("survival")
    await set_motd(ctx, "one")
    changes = ctx.backups.changes
    await changes.undo(user="tester")
    await set_motd(ctx, "new version", history="clear_redo")
    assert changes.redo_stack() == []
    assert changes.undo_stack() == []


async def test_a_failed_change_is_not_on_the_stack(core):
    ctx = core.get_server("survival")

    async def broken(job):
        raise OSError("disk full")

    with pytest.raises(SafeChangeError):
        await run_safe_change(ctx.server, ctx.backups, SafeChange(title="Fail", change=broken))
    assert ctx.backups.changes.undo_stack() == []


async def test_undo_puts_back_only_what_the_change_touched(core):
    ctx = core.get_server("creative")
    level = ctx.config.server_dir / "world" / "level.dat"
    await set_motd(ctx, "one", backup_includes=["server.properties"])
    level.write_bytes(b"played since")
    await ctx.backups.changes.undo(user="tester")
    assert motd(ctx) != "one"
    assert level.read_bytes() == b"played since"


async def test_restoring_a_backup_is_a_change_and_restore_world_keeps_its_scope(core):
    ctx = core.get_server("creative")
    level = ctx.config.server_dir / "world" / "level.dat"
    old = await ctx.backups.create(name="old", user="tester")
    level.write_bytes(b"newer world")
    await ctx.backups.restore(old["id"], user="tester", only={"world"})
    (entry,) = ctx.backups.changes.undo_stack()
    assert entry["scope"] == ["world"]
    await set_motd(ctx, "after", backup_includes=["server.properties"])
    await ctx.backups.changes.undo(user="tester")  # the motd
    await ctx.backups.changes.undo(user="tester")  # the world restore
    assert level.read_bytes() == b"newer world"


async def test_a_change_whose_backup_is_gone_drops_off_with_everything_beneath(core):
    ctx = core.get_server("survival")
    for name in ("one", "two", "three"):
        await set_motd(ctx, name)
    changes = ctx.backups.changes
    middle = changes.undo_stack()[1]
    await ctx.backups.delete(middle["backup_id"], user="tester")
    assert titles(changes.undo_stack()) == ["Setting the motd to three"]


async def test_each_server_has_its_own_stacks(core):
    survival = core.get_server("survival")
    creative = core.get_server("creative")
    await set_motd(survival, "one")
    assert creative.backups.changes.undo_stack() == []
    with pytest.raises(ChangeError):
        await creative.backups.changes.undo(user="tester")


async def test_backups_made_before_a_change_are_labelled_by_it(core):
    ctx = core.get_server("survival")
    await set_motd(ctx, "one")
    manual = await ctx.backups.create(name="by-hand", user="tester")
    labels = {b["id"]: b["label"] for b in ctx.backups.list_backups()}
    assert "Before setting the motd to one" in labels.values()
    assert labels[manual["id"]] is None


async def test_undo_and_redo_through_the_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    from .conftest import PASSWORD

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    config = build_multi_config(tmp_path)
    path = config.for_server("creative").server_dir / "server.properties"
    with TestClient(create_app(config)) as client:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        base = "/api/servers/creative"
        first = client.post(f"{base}/backups", json={"name": "first"}).json()
        path.write_text("server-port=1\n")
        second = client.post(f"{base}/backups", json={"name": "second"}).json()
        for backup in (first, second):
            restored = client.post(f"{base}/backups/{backup['id']}/restore", json={"confirm": True})
            assert restored.status_code == 200, restored.text
        assert "server-port=1" in path.read_text()

        stacks = client.get(f"{base}/changes").json()
        assert [c["title"][-10:] for c in stacks["undo"]] == ["second.zip", "-first.zip"]
        assert stacks["redo"] == []

        undone = client.post(f"{base}/changes/undo", json={})
        assert undone.status_code == 200, undone.text
        assert "server-port=25566" in path.read_text()
        undone = client.post(f"{base}/changes/undo", json={})
        assert "server-port=1" in path.read_text()

        stacks = client.get(f"{base}/changes").json()
        assert [c["title"][-10:] for c in stacks["redo"]] == ["-first.zip", "second.zip"]
        redone = client.post(f"{base}/changes/redo", json={})
        assert redone.status_code == 200, redone.text
        assert "server-port=25566" in path.read_text()

        # The older route undoes a job only while it is the newest change.
        newest = client.get(f"{base}/changes").json()["undo"][0]
        older = client.post(f"{base}/backups/{first['id']}/restore", json={"confirm": True}).json()
        assert client.post(f"/api/jobs/{newest['job_id']}/undo").status_code == 409
        assert client.post(f"/api/jobs/{older['job_id']}/undo").status_code == 200

        empty = client.post("/api/servers/survival/changes/redo", json={})
        assert empty.status_code == 409
