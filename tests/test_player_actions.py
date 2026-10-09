"""The Players page's buttons: whitelist, operator, kick, ban and unban.

Every button builds a fixed Minecraft command from a checked name and sends
it through the same validation as any console command. An action is
"sent" until the server's console confirms it, and only then "done".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent import servertypes
from agent.core import AgentCore
from agent.minecraft import commands, playeractions
from agent.minecraft.playeractions import PlayerActionError, build_command

from .conftest import build_multi_config
from .test_multi_server import wait_for


# ------------------------------------------------------------ building
@pytest.mark.parametrize(
    "kind, name, reason, expected",
    [
        ("whitelist_add", "Alex", "", "whitelist add Alex"),
        ("whitelist_remove", "Alex", "", "whitelist remove Alex"),
        ("op", "Steve_2", "", "op Steve_2"),
        ("deop", "Steve_2", "", "deop Steve_2"),
        ("kick", "Alex", "", "kick Alex"),
        ("kick", "Alex", "Be nice", "kick Alex Be nice"),
        ("ban", ".BedrockGuy", "Griefing", "ban .BedrockGuy Griefing"),
        ("pardon", "Alex", "", "pardon Alex"),
    ],
)
def test_each_button_builds_the_plain_minecraft_command(kind, name, reason, expected):
    assert build_command(kind, name, reason) == expected


@pytest.mark.parametrize(
    "name",
    ["", "a" * 17, "Alex; stop", "Alex\nstop", "Al ex", "@a", "@e[type=player]", "../x", "Alex§"],
)
def test_a_name_that_isnt_a_minecraft_name_is_refused(name):
    with pytest.raises(PlayerActionError):
        build_command("op", name)


@pytest.mark.parametrize("reason", ["two\nlines", "x" * 101, "$(stop)", "a;b", "ü"])
def test_a_reason_outside_one_plain_short_line_is_refused(reason):
    with pytest.raises(PlayerActionError):
        build_command("ban", "Alex", reason)


def test_only_kick_and_ban_take_a_reason():
    with pytest.raises(PlayerActionError):
        build_command("op", "Alex", "because")


def test_an_unknown_action_is_refused():
    with pytest.raises(PlayerActionError):
        build_command("stop", "Alex")


def test_every_built_command_passes_console_validation():
    for kind in playeractions.ACTIONS:
        command = build_command(kind, "Alex", "Bye" if kind in ("kick", "ban") else "")
        assert commands.validate(command, confirm=True).raw == command


# ------------------------------------------------------------ lists
def test_lists_come_from_minecrafts_files(tmp_path):
    (tmp_path / "ops.json").write_text('[{"uuid": "u", "name": "Alex", "level": 4}]')
    (tmp_path / "banned-players.json").write_text("not json")
    lists = playeractions.lists(tmp_path)
    assert lists["ops"]["players"] == [{"name": "Alex", "uuid": "u", "level": 4}]
    # A missing file is "not there yet", not an empty list.
    assert lists["whitelist"]["players"] is None and lists["whitelist"]["reason"]
    assert lists["banned"]["players"] is None and "couldn't be read" in lists["banned"]["reason"]


# ------------------------------------------------------------ with a server
@pytest.fixture
async def running(tmp_path):
    core = AgentCore(build_multi_config(tmp_path))
    ctx = core.servers["survival"]
    await ctx.start()
    await ctx.server.start()
    assert await ctx.server.wait_online(20)
    try:
        yield ctx
    finally:
        await ctx.server.stop()
        await ctx.stop()
        await core.jobs.stop()
        core.db.close()


async def settle(ctx, pending):
    assert await wait_for(lambda: ctx.player_actions.get(pending.id).state != "sent", 10)
    return ctx.player_actions.get(pending.id)


async def test_an_action_is_sent_and_then_done_when_the_console_confirms(running, monkeypatch):
    checked = []
    real = playeractions.validate
    monkeypatch.setattr(
        playeractions,
        "validate",
        lambda cmd, confirm=False: checked.append(cmd) or real(cmd, confirm),
    )
    events = []

    async def collect(event):
        events.append(event)

    running.bus.subscribe(collect)
    pending = await running.player_actions.send("whitelist_add", "Alex")
    assert checked == ["whitelist add Alex"]  # went through console validation
    assert pending.state == "sent"
    done = await settle(running, pending)
    assert done.state == "done"
    assert "Added Alex to the whitelist" in done.message
    # The list is read back from Minecraft's file.
    names = [
        p["name"] for p in playeractions.lists(running.config.server_dir)["whitelist"]["players"]
    ]
    assert names == ["Alex"]
    assert await wait_for(lambda: any(e.type == "player_action" for e in events))
    running.bus.unsubscribe(collect)


async def test_nothing_changed_is_reported_as_that(running):
    await settle(running, await running.player_actions.send("op", "Alex"))
    again = await settle(running, await running.player_actions.send("op", "Alex"))
    assert again.state == "unchanged"


async def test_a_failed_answer_is_reported_as_failed(running):
    result = await settle(
        running, await running.player_actions.send("kick", "Nobody", confirm=True)
    )
    assert result.state == "failed"


async def test_kick_removes_an_online_player(running):
    await running.server.send_command("fakejoin Alex")
    assert await wait_for(lambda: running.players.online_count() == 1)
    result = await settle(
        running, await running.player_actions.send("kick", "Alex", "Bye", confirm=True)
    )
    assert result.state == "done"
    assert await wait_for(lambda: running.players.online_count() == 0)


async def test_kick_and_ban_need_confirming(running):
    for kind in ("kick", "ban"):
        with pytest.raises(PlayerActionError):
            await running.player_actions.send(kind, "Alex")


async def test_a_bad_name_never_reaches_the_console(running, monkeypatch):
    sent = []

    async def spy(command, **kwargs):
        sent.append(command)

    monkeypatch.setattr(running.server, "send_command", spy)
    for name in ("Alex stop", "Alex\nstop", "@a"):
        with pytest.raises(PlayerActionError):
            await running.player_actions.send("op", name)
    with pytest.raises(PlayerActionError):
        await running.player_actions.send("ban", "Alex", "x\nstop", confirm=True)
    monkeypatch.undo()
    assert sent == []


async def test_no_answer_stays_unconfirmed(running, monkeypatch):
    async def swallow(command, **kwargs):
        return None

    monkeypatch.setattr(running.server, "send_command", swallow)
    pending = await running.player_actions.send("op", "Alex")
    pending.sent_at -= playeractions.CONFIRM_SECONDS + 1
    # Never "done" without the console saying so.
    assert running.player_actions.get(pending.id).state == "no_answer"
    monkeypatch.undo()


async def test_actions_need_a_running_server(tmp_path):
    core = AgentCore(build_multi_config(tmp_path))
    ctx = core.servers["survival"]
    try:
        with pytest.raises(PlayerActionError):
            await ctx.player_actions.send("op", "Alex")
    finally:
        await core.jobs.stop()
        core.db.close()


# ------------------------------------------------------------ the API
def test_the_api_refuses_bad_input_before_anything_runs(multi_client):
    url = "/api/servers/survival/players/actions"
    assert multi_client.post(url, json={"action": "stop", "name": "Alex"}).status_code == 422
    assert multi_client.post(url, json={"action": "op", "name": "Alex stop"}).status_code == 400
    # The server isn't running.
    response = multi_client.post(url, json={"action": "op", "name": "Alex"})
    assert response.status_code == 400 and "running" in response.json()["detail"]


def test_players_lists_say_when_minecraft_hasnt_written_them(multi_client):
    body = multi_client.get("/api/servers/survival/players").json()
    assert body["running"] is False
    assert body["lists"]["whitelist"]["players"] is None
    assert body["actions"] == []


# ------------------------------------------------------------ answers
class _Server:
    running = True
    config = SimpleNamespace(server_type=servertypes.get("fabric"))

    state = SimpleNamespace(value="ONLINE")

    def __init__(self):
        self.sent = []

    async def send_command(self, command):
        self.sent.append(command)


class _Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _line(message, source="stdout"):
    from agent.minecraft.console import parse_line

    return parse_line(f"[12:00:00] [Server thread/INFO]: {message}", 1, source)


async def test_a_chat_message_with_the_same_words_does_not_confirm_an_action():
    actions = playeractions.PlayerActions(_Server(), _Bus())
    pending = await actions.send("whitelist_add", "Bob")
    # A player typing Minecraft's answer in chat, and another operator's
    # echoed command, are not the server answering this button.
    await actions.handle(None, _line("<Steve> Added Bob to the whitelist"))
    await actions.handle(None, _line("[Steve: Added Bob to the whitelist]"))
    assert actions.get(pending.id).state == "sent"
    await actions.handle(None, _line("Added Bob to the whitelist"))
    assert actions.get(pending.id).state == "done"


async def test_the_answer_is_matched_whatever_the_names_case():
    actions = playeractions.PlayerActions(_Server(), _Bus())
    pending = await actions.send("op", "alex")
    # Minecraft prints the account's own spelling.
    await actions.handle(None, _line("Made Alex a server operator"))
    assert actions.get(pending.id).state == "done"
