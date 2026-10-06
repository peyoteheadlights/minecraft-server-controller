"""The Game settings page: editing server.properties without losing anything.

The file is Minecraft's own, so everything the page doesn't edit has to
survive byte for byte: comments, blank lines, key order, keys this app
doesn't know, escapes and odd line endings. Values are checked before
anything is written, the port with the port manager, and a copy of the old
file is kept as the change's undo.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.core import AgentCore
from agent.minecraft import properties

from .conftest import build_multi_config

ORIGINAL = (
    "#Minecraft server properties\n"
    "#Mon Oct 05 21:00:00 UTC 2026\n"
    "enable-jmx-monitoring=false\n"
    "rcon.port=25575\n"
    "level-seed=\n"
    "gamemode=survival\n"
    "motd=A Minecraft Server\n"
    "# a comment someone wrote by hand\n"
    "resource-pack=https\\://example.com/pack.zip\n"
    "some-mod-setting=keep me\n"
    "difficulty=easy\n"
    "server-port=25565\n"
    "\n"
    "max-players=20\n"
)


def write(folder, text=ORIGINAL):
    # Bytes, not write_text: on Windows write_text turns every "\n" into
    # "\r\n", and these tests are about the file's exact bytes.
    (folder / "server.properties").write_bytes(text.encode("utf-8"))


# ---------------------------------------------------------------- the format
def test_a_change_keeps_comments_unknown_keys_and_order(tmp_path):
    write(tmp_path)
    edited, changed = properties.apply_form(tmp_path, {"difficulty": "hard", "max-players": 8})
    assert changed == {"difficulty": "hard", "max-players": "8"}
    expected = ORIGINAL.replace("difficulty=easy", "difficulty=hard").replace(
        "max-players=20", "max-players=8"
    )
    assert edited.text() == expected


def test_a_key_the_file_lacks_is_added_at_the_end(tmp_path):
    write(tmp_path, "#hello\nmotd=Hi")  # no newline at the end
    edited, _ = properties.apply_form(tmp_path, {"pvp": False})
    assert edited.text() == "#hello\nmotd=Hi\npvp=false\n"


def test_windows_line_endings_are_kept(tmp_path):
    (tmp_path / "server.properties").write_bytes(b"motd=Hi\r\nmax-players=20\r\n")
    edited, _ = properties.apply_form(tmp_path, {"max-players": 5})
    edited.write(tmp_path / "server.properties")
    assert (tmp_path / "server.properties").read_bytes() == b"motd=Hi\r\nmax-players=5\r\n"


def test_escapes_are_read_and_written_the_way_minecraft_does():
    parsed = properties.PropertiesFile("motd=\\u00A7aGreen \\: server\n")
    assert parsed.get("motd") == "§aGreen : server"
    parsed.set("motd", "Café: open")
    assert parsed.text() == "motd=Caf\\u00E9\\: open\n"


def test_bytes_that_are_not_utf8_survive_untouched(tmp_path):
    raw = b"motd=Hi\nweird=\xff\xfe\nmax-players=20\n"
    (tmp_path / "server.properties").write_bytes(raw)
    edited, _ = properties.apply_form(tmp_path, {"max-players": 3})
    edited.write(tmp_path / "server.properties")
    assert (tmp_path / "server.properties").read_bytes() == raw.replace(b"=20", b"=3")


def test_an_unchanged_value_rewrites_nothing(tmp_path):
    write(tmp_path)
    edited, changed = properties.apply_form(tmp_path, {"difficulty": "easy"})
    assert changed == {}
    assert edited.text() == ORIGINAL


@pytest.mark.parametrize(
    "key, value",
    [
        ("difficulty", "nightmare"),
        ("gamemode", "god"),
        ("max-players", 0),
        ("max-players", "12abc"),
        ("max-players", True),
        ("view-distance", 99),
        ("pvp", "yes"),
        ("motd", "two\nlines"),
        ("motd", "x" * 151),
        ("server-port", 80),
        ("server-port", 70000),
        ("online-mode", False),  # not one of the form's keys
    ],
)
def test_a_bad_value_is_refused_and_nothing_is_written(tmp_path, key, value):
    write(tmp_path)
    with pytest.raises(properties.FormError) as caught:
        companion = {"max-players": 5} if key != "max-players" else {"pvp": False}
        properties.apply_form(tmp_path, {**companion, key: value})
    assert key in caught.value.problems
    assert (tmp_path / "server.properties").read_text(encoding="utf-8") == ORIGINAL


def test_the_seed_is_read_only_once_the_world_exists(tmp_path):
    write(tmp_path)
    (tmp_path / "world").mkdir()
    (tmp_path / "world" / "level.dat").write_bytes(b"x")
    view = properties.form_view(tmp_path)
    seed = next(f for f in view["fields"] if f["key"] == "level-seed")
    assert seed["read_only"] == "world_exists"
    with pytest.raises(properties.FormError) as caught:
        properties.apply_form(tmp_path, {"level-seed": "12345"})
    assert "level-seed" in caught.value.problems


def test_the_seed_can_be_set_before_the_world_exists(tmp_path):
    write(tmp_path)
    _, changed = properties.apply_form(tmp_path, {"level-seed": "12345"})
    assert changed == {"level-seed": "12345"}


def test_a_key_the_file_does_not_set_is_reported_as_not_set(tmp_path):
    write(tmp_path, "motd=Hi\n")
    view = properties.form_view(tmp_path)
    pvp = next(f for f in view["fields"] if f["key"] == "pvp")
    # Not set is not the same as "true": the value is null, and Minecraft's
    # own default is given separately.
    assert pvp["value"] is None and pvp["set"] is False
    assert pvp["minecraft_default"] == "true"


def test_a_value_minecraft_would_not_accept_is_flagged_not_guessed(tmp_path):
    write(tmp_path, "difficulty=extreme\ngamemode=1\n")
    view = properties.form_view(tmp_path)
    fields = {f["key"]: f for f in view["fields"]}
    assert fields["difficulty"]["value"] is None and fields["difficulty"]["problem"]
    # Old servers wrote numbers, which Minecraft still reads.
    assert fields["gamemode"]["value"] == "creative"


def test_raw_text_still_checks_the_known_keys():
    with pytest.raises(properties.PropertiesError):
        properties.check_raw_text("difficulty=extreme\nanything=goes\n")
    parsed = properties.check_raw_text("difficulty=hard\nanything=goes\n")
    assert parsed.get("anything") == "goes"


def test_the_port_is_checked_with_the_port_manager(tmp_path):
    write(tmp_path)
    with pytest.raises(properties.FormError) as caught:
        properties.apply_form(
            tmp_path, {"server-port": 25570}, lambda port: "the server 'Creative' uses it"
        )
    assert "Creative" in caught.value.problems["server-port"]


# ---------------------------------------------------------------- the API
def test_saving_keeps_a_copy_and_offers_undo(multi_client, multi):
    folder = multi.for_server("survival").server_dir
    write(folder)
    response = multi_client.put(
        "/api/servers/survival/game-settings", json={"values": {"difficulty": "hard", "pvp": False}}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] == {"difficulty": "hard", "pvp": "false"}
    assert body["undo"]["kind"] == "restore_backup"
    text = (folder / "server.properties").read_text(encoding="utf-8")
    assert "difficulty=hard" in text and "some-mod-setting=keep me" in text
    assert "# a comment someone wrote by hand" in text
    backups = multi_client.get("/api/servers/survival/backups").json()["backups"]
    safety = next(b for b in backups if b["name"] == body["safety_backup"])
    assert safety["kind"] == "safety"


def test_a_port_another_server_uses_is_refused_by_name(multi_client, multi):
    folder = multi.for_server("survival").server_dir
    write(folder)
    response = multi_client.put(
        "/api/servers/survival/game-settings", json={"values": {"server-port": 25566}}
    )
    assert response.status_code == 400
    assert "Creative" in response.json()["problems"]["server-port"]
    assert "server-port=25565" in (folder / "server.properties").read_text(encoding="utf-8")


def test_the_view_says_what_the_file_says(multi_client, multi):
    write(multi.for_server("survival").server_dir)
    view = multi_client.get("/api/servers/survival/game-settings").json()
    fields = {f["key"]: f for f in view["fields"]}
    assert fields["difficulty"]["value"] == "easy"
    assert fields["max-players"]["value"] == 20
    assert view["running"] is False and view["restart_needed"] is False
    assert "some-mod-setting=keep me" in view["text"]


def test_saving_raw_text_works_and_still_refuses_bad_known_values(multi_client, multi):
    folder = multi.for_server("survival").server_dir
    write(folder)
    bad = multi_client.put(
        "/api/servers/survival/game-settings/raw", json={"text": "difficulty=extreme\n"}
    )
    assert bad.status_code == 400
    good = multi_client.put(
        "/api/servers/survival/game-settings/raw",
        json={"text": ORIGINAL.replace("keep me", "changed by hand")},
    )
    assert good.status_code == 200, good.text
    assert "some-mod-setting=changed by hand" in (folder / "server.properties").read_text(
        encoding="utf-8"
    )


async def test_a_change_while_running_waits_for_a_restart(tmp_path):
    from agent import gamesettings

    core = AgentCore(build_multi_config(tmp_path))
    ctx = core.servers["survival"]
    await ctx.start()
    try:
        await ctx.server.start()
        assert await ctx.server.wait_online(20)
        await asyncio.sleep(0.05)
        result = await gamesettings.save(ctx, updates={"difficulty": "hard"})
        assert result["running"] is True
        # The file changed after the server started: what it runs is not
        # what the file says until it restarts.
        assert result["restart_needed"] is True
        # The server was never stopped for this.
        assert ctx.server.running
    finally:
        await ctx.server.stop()
        await ctx.stop()
        await core.jobs.stop()
        core.db.close()
