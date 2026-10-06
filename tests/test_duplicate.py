"""Duplicating a server: same software, add-ons, config and game settings,
with a new name, folder, color and port, and a copied or fresh world.

The copy only ever reads the source's own folder and only ever writes inside
the new one, and it never reads a world Minecraft is writing to.
"""

from __future__ import annotations

import os
import sys

import pytest

from agent import duplicate
from agent.core import AgentCore
from agent.duplicate import DuplicateError
from agent.jobs import RUNNING, SUCCEEDED
from agent.minecraft.state import ServerState
from agent.security.paths import PathSafetyError

from .conftest import build_multi_config
from .test_multi_server import wait_for


@pytest.fixture
async def core(tmp_path):
    agent = AgentCore(build_multi_config(tmp_path))
    for ctx in agent.servers.values():
        await ctx.start()
    try:
        yield agent
    finally:
        for ctx in list(agent.servers.values()):
            if ctx.server.running:
                await ctx.server.stop()
            await ctx.stop()
        await agent.jobs.stop()
        agent.db.close()


async def finish(core, job):
    assert await wait_for(lambda: core.jobs.get(job.id).state != RUNNING, 30)
    return core.jobs.get(job.id)


def snapshot(folder):
    """Every file under a folder with its bytes."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


async def test_a_copy_has_the_same_setup_and_world_but_its_own_port_and_color(core, tmp_path):
    source = core.servers["survival"]
    folder = source.config.server_dir
    (folder / "mods" / "lithium.jar").write_bytes(b"mod")
    (folder / "config" / "lithium.properties").write_text("a=1\n")
    (folder / "server.properties").write_text(
        "#keep\nserver-port=25565\nmotd=Hello\nlevel-seed=42\n", encoding="utf-8"
    )
    target = tmp_path / "servers" / "Survival copy"
    job = await duplicate.start_duplicate(
        core, source, name="Survival copy", directory=str(target), world="copy"
    )
    done = await finish(core, job)
    assert done.state == SUCCEEDED, done.message
    new_id = done.result["server_id"]
    copy = core.servers[new_id]

    assert (target / "mods" / "lithium.jar").read_bytes() == b"mod"
    assert (target / "config" / "lithium.properties").read_text() == "a=1\n"
    assert (target / "fabric-server-launch.jar").is_file()
    assert (target / "world" / "level.dat").read_bytes() == b"x" * 2048
    # History stays with the old server.
    assert not (target / "logs").exists() and not (target / "crash-reports").exists()
    # Its own port, free and not another server's, written into its game settings.
    port = done.result["port"]
    assert port not in (25565, 25566)
    assert copy.config.server.port == port
    text = (target / "server.properties").read_text(encoding="utf-8")
    assert f"server-port={port}" in text and "level-seed=42" in text and "#keep" in text
    # Its own color, the same launch set-up.
    assert copy.color and copy.color not in {source.color, core.servers["creative"].color}
    assert copy.config.server.raw_command == source.config.server.raw_command
    # The source is untouched.
    assert "server-port=25565" in (folder / "server.properties").read_text(encoding="utf-8")


async def test_a_fresh_world_leaves_the_world_and_its_seed_behind(core, tmp_path):
    source = core.servers["survival"]
    (source.config.server_dir / "server.properties").write_text(
        "server-port=25565\nlevel-seed=42\n", encoding="utf-8"
    )
    target = tmp_path / "Fresh"
    done = await finish(
        core,
        await duplicate.start_duplicate(
            core, source, name="Fresh", directory=str(target), world="fresh"
        ),
    )
    assert done.state == SUCCEEDED, done.message
    for name in ("world", "world_nether", "world_the_end"):
        assert not (target / name).exists()
    assert "level-seed=\n" in (target / "server.properties").read_text(encoding="utf-8")
    assert (target / "mods").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
async def test_links_are_never_followed_out_of_the_source(core, tmp_path):
    source = core.servers["survival"]
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, source.config.server_dir / "linked-folder")
    os.symlink(outside / "secret.txt", source.config.server_dir / "linked-file.txt")
    target = tmp_path / "Copy"
    done = await finish(
        core,
        await duplicate.start_duplicate(
            core, source, name="Copy", directory=str(target), world="copy"
        ),
    )
    assert done.state == SUCCEEDED, done.message
    assert not (target / "linked-folder").exists()
    assert not (target / "linked-file.txt").exists()
    assert "secret" not in str(snapshot(target).values())


async def test_nothing_is_written_outside_the_new_folder(core, tmp_path):
    source = core.servers["survival"]
    before = snapshot(tmp_path)
    target = tmp_path / "servers" / "Copy"
    done = await finish(
        core,
        await duplicate.start_duplicate(
            core, source, name="Copy", directory=str(target), world="copy"
        ),
    )
    assert done.state == SUCCEEDED, done.message
    after = snapshot(tmp_path)
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    allowed = ("servers/Copy/", "mcsc-data/", "config.yaml")
    assert changed and all(path.startswith(allowed) for path in changed), sorted(changed)


def test_a_path_that_climbs_out_is_refused_by_the_copier(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x")
    with pytest.raises(PathSafetyError):
        duplicate._copy_files([(source, "../escaped.txt", 1)], tmp_path / "target", lambda n: None)
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.parametrize("where", ["inside_other", "not_empty"])
async def test_an_unsafe_folder_is_refused_before_anything_is_copied(core, tmp_path, where):
    source = core.servers["survival"]
    if where == "inside_other":
        target = core.servers["creative"].config.server_dir / "nested"
    else:
        target = tmp_path / "busy"
        target.mkdir()
        (target / "something.txt").write_text("x")
    with pytest.raises((PathSafetyError, DuplicateError)):
        await duplicate.start_duplicate(
            core, source, name="Copy", directory=str(target), world="copy"
        )
    assert "Copy" not in [ctx.name for ctx in core.servers.values()]


async def test_a_server_that_is_starting_is_not_copied(core, tmp_path, monkeypatch):
    source = core.servers["survival"]
    monkeypatch.setattr(type(source.server), "running", property(lambda self: True))
    source.server.state = ServerState.STARTING
    with pytest.raises(DuplicateError):
        await duplicate.start_duplicate(
            core, source, name="Copy", directory=str(tmp_path / "Copy"), world="copy"
        )
    monkeypatch.undo()
    source.server.state = ServerState.OFFLINE


async def test_a_copy_that_does_not_check_out_is_removed_again(core, tmp_path, monkeypatch):
    source = core.servers["survival"]
    monkeypatch.setattr(duplicate, "_check_copy", lambda files, target: (False, "a file differs"))
    target = tmp_path / "Broken"
    done = await finish(
        core,
        await duplicate.start_duplicate(
            core, source, name="Broken", directory=str(target), world="copy"
        ),
    )
    assert done.state != SUCCEEDED
    assert not target.exists()
    assert sorted(core.servers) == ["creative", "survival"]


async def test_a_running_source_is_saved_and_paused_for_the_copy(core, tmp_path, monkeypatch):
    source = core.servers["survival"]
    await source.server.start()
    assert await source.server.wait_online(20)
    sent = []
    real = source.server.send_command

    async def spy(command, **kwargs):
        sent.append(command)
        return await real(command, **kwargs)

    monkeypatch.setattr(source.server, "send_command", spy)
    done = await finish(
        core,
        await duplicate.start_duplicate(
            core, source, name="Live", directory=str(tmp_path / "Live"), world="copy"
        ),
    )
    monkeypatch.undo()
    assert done.state == SUCCEEDED, done.message
    assert [c for c in sent if c.startswith("save")] == ["save-all flush", "save-off", "save-on"]


def test_the_suggestion_is_a_free_name_and_folder(multi_client, multi):
    body = multi_client.get("/api/servers/survival/duplicate").json()
    assert body["name"] == "Survival copy"
    assert body["directory"].endswith("Survival copy")
    assert body["world_folders"] == ["world", "world_nether", "world_the_end"]


def test_the_api_refuses_a_world_choice_it_doesnt_know(multi_client, tmp_path):
    response = multi_client.post(
        "/api/servers/survival/duplicate",
        json={"name": "X", "directory": str(tmp_path / "X"), "world": "maybe"},
    )
    assert response.status_code == 422
