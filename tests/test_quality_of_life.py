"""Phase 5: the quality-of-life features.

Auto-sleep, world undo, the chat box and the getting-started checklist.
The two house rules decide most of what is checked here: a server is never
stopped on a player count nobody established, and the chat box can no more
reach the operating system than the console can.
"""

import asyncio
import time

import pytest

from agent.autosleep import WARN_SECONDS, AutoSleep
from agent.backups.manager import BackupError
from agent.checklist import dismiss, status
from agent.core import AgentCore
from agent.minecraft.chat import ChatError, ChatLog, check_message, parse_chat, say
from agent.minecraft.console import ConsoleLine
from agent.minecraft.state import ExitReason
from agent.worldundo import WorldUndoError, played_seconds, restore, timeline

from .conftest import build_multi_config


@pytest.fixture
async def core(tmp_path):
    core = AgentCore(build_multi_config(tmp_path))
    yield core
    for ctx in core.servers.values():
        await ctx.autosleep.stop()
        if ctx.server.running:
            await ctx.server.stop(actor="test")
    await core.jobs.stop()
    core.db.close()


@pytest.fixture
async def ctx(core):
    return core.servers["survival"]


async def online(ctx):
    """Bring this server up and wait until it says it is online."""
    await ctx.server.start(actor="test")
    assert await ctx.server.wait_online(timeout=20)
    return ctx


def line(text, source="stdout", seq=1):
    return ConsoleLine(seq=seq, ts=time.time(), raw=text, source=source, level="INFO", message=text)


# ------------------------------------------------------------- auto-sleep
async def test_autosleep_is_off_until_a_server_turns_it_on(ctx):
    assert ctx.config.server.autosleep is False
    assert await ctx.autosleep.check() == "off"
    assert ctx.autosleep.status()["enabled"] is False


def silence_list(ctx, monkeypatch):
    """Make "list" go unanswered, as when a plugin replaced the command."""
    real = ctx.server.send_command

    async def send(command, internal=False):
        if command == "list":
            return True
        return await real(command, internal=internal)

    monkeypatch.setattr(ctx.server, "send_command", send)
    monkeypatch.setattr("agent.autosleep.LIST_ANSWER_SECONDS", 0.3)


async def test_autosleep_never_stops_a_server_while_the_count_is_unknown(ctx, monkeypatch):
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    silence_list(ctx, monkeypatch)
    # Nothing has established the count: no join, no leave, and Minecraft
    # doesn't answer "list".
    assert ctx.players.online_count() is None

    assert await ctx.autosleep.check() == "unknown"
    # Even long after the wait would have passed, because "empty" was never
    # a fact to begin with.
    assert await ctx.autosleep.check(now=time.time() + 24 * 3600) == "unknown"
    assert ctx.autosleep.empty_since is None
    assert ctx.autosleep.status()["list_answered"] is False
    assert ctx.server.running is True


async def test_autosleep_asks_minecraft_when_nobody_ever_joined(ctx):
    """A server started and never joined has no join or leave to go on, so
    auto-sleep asks with "list" and takes Minecraft's answer."""
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    assert ctx.players.online_count() is None
    now = time.time()
    assert await ctx.autosleep.check(now=now) == "waiting"
    assert ctx.players.online_count() == 0
    assert ctx.autosleep.status()["list_answered"] is True
    # With a one-minute wait the warning goes out at once, then the stop.
    assert await ctx.autosleep.check(now=now + 15) == "warned"
    assert await ctx.autosleep.check(now=now + 61) == "slept"
    assert ctx.server.running is False


async def test_autosleep_does_not_stop_when_minecraft_says_someone_is_on(ctx):
    """The tracker can miss a join (a plugin may change the join message).
    Minecraft's own list is asked before the stop and wins."""
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    # Somebody really is on, but the tracker never saw them join.
    await ctx.server.send_command("fakejoin Steve", internal=True)
    for _ in range(50):
        if ctx.players.online_count():
            break
        await asyncio.sleep(0.05)
    await ctx.players.player_left("Steve")
    assert ctx.players.online_count() == 0

    now = time.time()
    assert await ctx.autosleep.check(now=now) == "waiting"
    assert await ctx.autosleep.check(now=now + 120) == "players"
    assert ctx.server.running is True
    assert ctx.players.online_count() == 1


async def test_autosleep_never_stops_when_list_goes_unanswered(ctx, monkeypatch):
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    silence_list(ctx, monkeypatch)
    now = time.time()
    assert await ctx.autosleep.check(now=now) == "waiting"
    assert await ctx.autosleep.check(now=now + 3600) == "unknown"
    assert ctx.server.running is True


async def test_autosleep_never_stops_a_server_people_are_playing_on(ctx):
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    await ctx.players.player_joined("Alex")
    assert ctx.players.online_count() == 1

    assert await ctx.autosleep.check() == "players"
    assert await ctx.autosleep.check(now=time.time() + 24 * 3600) == "players"
    assert ctx.server.running is True


async def test_autosleep_stops_an_empty_server_once_the_wait_has_passed(ctx):
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 30)
    events = []
    ctx.core.bus.subscribe(lambda e: events.append(e))
    await online(ctx)
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    assert ctx.players.online_count() == 0

    now = time.time()
    assert await ctx.autosleep.check(now=now) == "waiting"
    assert ctx.autosleep.empty_since == now
    # Still waiting halfway through.
    assert await ctx.autosleep.check(now=now + 15 * 60) == "waiting"
    # Warned a minute before the stop, not stopped yet.
    assert await ctx.autosleep.check(now=now + 30 * 60 - WARN_SECONDS + 1) == "warned"
    assert ctx.server.running is True

    assert await ctx.autosleep.check(now=now + 30 * 60) == "slept"
    assert ctx.server.running is False
    # A planned stop, never a crash, and the dashboard can say why.
    assert ctx.server.last_exit_reason is ExitReason.SCHEDULED_STOP
    assert ctx.server.stopped_for_sleep is True
    stopped = [e for e in events if e.type == "autosleep_stopped"]
    assert stopped and stopped[0].data["empty_minutes"] == 30
    assert not [e for e in events if e.type == "server_crashed"]


async def test_autosleep_waits_for_a_change_that_is_running(ctx):
    ctx.config.set("server.autosleep", True)
    ctx.config.set("server.autosleep_minutes", 1)
    await online(ctx)
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    now = time.time()
    assert await ctx.autosleep.check(now=now) == "waiting"

    ctx.server.held_by = "Restoring a backup"
    assert await ctx.autosleep.check(now=now + 3600) == "waiting"
    assert ctx.server.running is True
    ctx.server.held_by = None


async def test_autosleep_forgets_the_wait_when_somebody_joins(ctx):
    ctx.config.set("server.autosleep", True)
    await online(ctx)
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    assert await ctx.autosleep.check() == "waiting"

    await ctx.players.player_joined("Steve")
    assert await ctx.autosleep.check() == "players"
    assert ctx.autosleep.empty_since is None


async def test_autosleep_does_nothing_while_the_server_is_off(ctx):
    ctx.config.set("server.autosleep", True)
    assert await ctx.autosleep.check() == "not_online"
    assert ctx.autosleep.status()["stops_in"] is None


async def test_autosleep_status_never_guesses_the_count(ctx):
    ctx.config.set("server.autosleep", True)
    state = ctx.autosleep.status()
    assert state["players_online"] is None
    assert state["players_verified"] is False


def test_autosleep_minutes_never_falls_below_one(ctx):
    ctx.config.set("server.autosleep_minutes", 0)
    assert AutoSleep(ctx).minutes == 1.0


# ------------------------------------------------------------- world undo
async def test_undo_always_takes_a_fresh_backup_before_restoring(ctx):
    world = ctx.config.server_dir / "world" / "level.dat"
    world.write_bytes(b"the world before")
    created = await ctx.backups.create(user="tester")
    world.write_bytes(b"the world after an afternoon")

    before = len(ctx.backups.list_backups())
    result = await restore(ctx, created["id"], user="tester")

    assert result["safety_backup"] is not None
    assert result["safety_backup"]["name"].startswith("safety-")
    assert len(ctx.backups.list_backups()) == before + 1
    assert world.read_bytes() == b"the world before"


async def test_undo_refuses_while_the_server_is_running(ctx):
    created = await ctx.backups.create(user="tester")
    await online(ctx)
    with pytest.raises(WorldUndoError, match="Stop Survival first"):
        await restore(ctx, created["id"], user="tester")


async def test_undo_does_not_offer_a_backup_that_did_not_check_out(ctx):
    created = await ctx.backups.create(user="tester")
    ctx.db.execute("UPDATE backups SET status = ? WHERE id = ?", ("failed", created["id"]))

    point = next(p for p in timeline(ctx)["points"] if p["backup_id"] == created["id"])
    assert point["checked"] is False
    with pytest.raises(WorldUndoError, match="not checked"):
        await restore(ctx, created["id"], user="tester")


async def test_undo_refuses_a_damaged_archive_without_touching_the_world(ctx):
    world = ctx.config.server_dir / "world" / "level.dat"
    world.write_bytes(b"the world as it is")
    created = await ctx.backups.create(user="tester")
    (ctx.config.backup_dir / created["name"]).write_bytes(b"not a zip")

    with pytest.raises(BackupError, match="did not verify"):
        await restore(ctx, created["id"], user="tester")
    assert world.read_bytes() == b"the world as it is"


async def test_undo_refuses_a_point_that_is_not_on_the_timeline(ctx):
    with pytest.raises(WorldUndoError, match="isn't on this server's timeline"):
        await restore(ctx, 9999, user="tester")


async def test_timeline_lists_checked_world_backups_newest_first(ctx):
    first = await ctx.backups.create(user="tester")
    second = await ctx.backups.create(user="tester")
    points = timeline(ctx)["points"]
    assert [p["backup_id"] for p in points] == [second["id"], first["id"]]
    assert all(p["checked"] for p in points)
    assert all(p["age_seconds"] >= 0 for p in points)


async def test_timeline_says_the_server_has_to_be_off(ctx):
    await ctx.backups.create(user="tester")
    assert timeline(ctx)["can_restore"] is True
    await online(ctx)
    state = timeline(ctx)
    assert state["server_running"] is True
    assert state["can_restore"] is False


async def test_undo_puts_back_the_world_and_leaves_mods_alone(ctx):
    """Restore world restores the world. A mod added since the backup stays,
    and so does a setting changed since."""
    base = ctx.config.server_dir
    (base / "world").mkdir(exist_ok=True)
    (base / "world" / "level.dat").write_bytes(b"old world")
    (base / "mods").mkdir(exist_ok=True)
    (base / "mods" / "old.jar").write_bytes(b"jar")
    created = await ctx.backups.create(user="tester")
    (base / "world" / "level.dat").write_bytes(b"new world")
    (base / "mods" / "added-since.jar").write_bytes(b"jar")
    (base / "server.properties").write_text("motd=changed since\n")

    await restore(ctx, created["id"], user="tester")

    assert (base / "world" / "level.dat").read_bytes() == b"old world"
    assert (base / "mods" / "added-since.jar").is_file()
    assert (base / "server.properties").read_text() == "motd=changed since\n"


async def test_undo_follows_the_level_name(ctx):
    """A world called "survival" in server.properties is the world, both in
    backups and on the timeline."""
    base = ctx.config.server_dir
    (base / "server.properties").write_text("level-name=survival\n")
    (base / "survival").mkdir()
    (base / "survival" / "level.dat").write_bytes(b"before")
    created = await ctx.backups.create(user="tester")
    assert "survival" in ctx.backups.get(created["id"])["includes"].split(",")
    assert [p["backup_id"] for p in timeline(ctx)["points"]] == [created["id"]]

    (base / "survival" / "level.dat").write_bytes(b"after")
    await restore(ctx, created["id"], user="tester")
    assert (base / "survival" / "level.dat").read_bytes() == b"before"


async def test_play_lost_counts_friends_playing_together_once(ctx):
    now = time.time()
    for name in ("Alex", "Sam", "Kim"):
        ctx.db.insert(
            "player_sessions",
            {
                "server_id": ctx.server_id,
                "username": name,
                "uuid": None,
                "joined_at": now - 3600,
                "left_at": now - 1800,
            },
        )
    # Three people for the same half hour: half an hour of the world changing.
    assert played_seconds(ctx, now - 7200, now) == pytest.approx(1800)


async def test_play_lost_is_unknown_when_nothing_was_recorded(ctx):
    now = time.time()
    # No sessions at all: how much was played is not known, not zero.
    assert played_seconds(ctx, now - 3600, now) is None
    await ctx.players.player_joined("Alex")
    await ctx.players.player_left("Alex")
    assert played_seconds(ctx, now - 3600, now) is not None


# -------------------------------------------------------------------- chat
def test_chat_reads_what_the_console_printed():
    assert parse_chat(line("<Alex> hello there")) == ("player", "Alex", "hello there")
    assert parse_chat(line("[Not Secure] <Alex> hi")) == ("player", "Alex", "hi")
    assert parse_chat(line("[Server] back in a bit")) == ("server", None, "back in a bit")
    assert parse_chat(line("* Alex waves")) == ("action", "Alex", "waves")
    # A Bedrock player's name keeps the prefix the server printed.
    assert parse_chat(line("<.Sam> hey"))[1] == ".Sam"


def test_chat_ignores_lines_that_are_not_chat():
    assert parse_chat(line('Done (1.234s)! For help, type "help"')) is None
    assert parse_chat(line("Alex joined the game")) is None
    # A command this app echoed is not chat, even when it begins with "say".
    assert parse_chat(line("say hello", source="command")) is None


def test_chat_cannot_be_faked_by_a_player():
    """A player's own message is never read as the server talking."""
    kind, name, text = parse_chat(line("<Alex> [Server] the server is closing"))
    assert kind == "player" and name == "Alex"
    assert text == "[Server] the server is closing"


def test_chat_log_keeps_the_recent_messages_in_order():
    log = ChatLog(maxlen=3)
    for text in ("<Alex> one", "<Alex> two", "not chat at all", "<Alex> three", "<Alex> four"):
        log.add(line(text))
    assert [m.text for m in log.tail(10)] == ["two", "three", "four"]
    assert [m.seq for m in log.since(log.tail(10)[0].seq)] == [3, 4]


def test_chat_refuses_what_a_console_command_could_not_carry():
    assert check_message("  hello  ") == "hello"
    for bad in ("", "   ", "say\nstop", "stop; shutdown -s", "`whoami`", "a" * 221):
        with pytest.raises(ChatError):
            check_message(bad)


async def test_chat_sends_go_through_command_validation(ctx, monkeypatch):
    """The chat box is a `say` command like any other, with the same checks."""
    await online(ctx)
    sent = []

    async def record(text, **kwargs):
        sent.append(text)
        return text

    monkeypatch.setattr(ctx.server, "send_command", record)

    await say(ctx.server, "back in a bit")
    assert sent == ["say back in a bit"]

    # Anything the command validator would refuse never reaches the server.
    sent.clear()
    for bad in ("stop\nop Alex", "say `date`", "hello\rstop"):
        with pytest.raises(ChatError):
            await say(ctx.server, bad)
    assert sent == []

    # Plain text that happens to read like a shell command is still only
    # ever chat: it reaches the game as the argument of `say`, nothing more.
    await say(ctx.server, "rm -rf is not a Minecraft command")
    assert sent == ["say rm -rf is not a Minecraft command"]


async def test_chat_needs_a_running_server(ctx):
    with pytest.raises(ChatError, match="has to be running"):
        await say(ctx.server, "anybody there")


async def test_chat_appears_only_once_the_console_prints_it(ctx):
    await online(ctx)
    await ctx.server.send_command("say hello everyone")
    # The echo of the command itself is not chat; only the server's own
    # "[Server] ..." line is, and that is what the log holds.
    assert all(m.kind != "player" for m in ctx.chat.tail(10))


# -------------------------------------------------------- getting started
async def test_checklist_ticks_only_what_the_app_measured(ctx, monkeypatch):
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/1/x")
    state = status(ctx)
    ids = [item["id"] for item in state["items"]]
    assert ids == ["server_ready", "backup_taken", "friend_joined", "alerts_on"]
    done = {item["id"]: item["done"] for item in state["items"]}
    assert done["backup_taken"] is False
    assert done["friend_joined"] is False
    assert done["alerts_on"] is False
    assert state["show"] is True

    await ctx.backups.create(user="tester")
    await ctx.players.player_joined("Alex")
    ctx.core.config.set("notifications.discord_enabled", True)
    state = status(ctx)
    done = {item["id"]: item["done"] for item in state["items"]}
    assert all(done.values())
    assert state["done"] == state["total"]


async def test_checklist_is_finished_for_good_once_everything_is_done(ctx, monkeypatch):
    monkeypatch.setenv("MCSC_DISCORD_WEBHOOK", "https://discord.com/api/webhooks/1/x")
    await ctx.backups.create(user="tester")
    await ctx.players.player_joined("Alex")
    ctx.core.config.set("notifications.discord_enabled", True)
    assert status(ctx)["finished"] is True

    # Switching alerts off again does not bring the card back.
    ctx.core.config.set("notifications.discord_enabled", False)
    state = status(ctx)
    assert state["finished"] is True
    assert state["show"] is False


async def test_an_alert_switch_that_cannot_deliver_is_not_ticked(ctx, monkeypatch):
    """Discord switched on with no webhook, or phone alerts on with no phone
    signed up, sends nothing, so "Alerts are on" would not be true."""
    monkeypatch.delenv("MCSC_DISCORD_WEBHOOK", raising=False)
    monkeypatch.setenv("MCSC_VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("MCSC_VAPID_PRIVATE_KEY", "priv")
    ctx.core.config.set("notifications.discord_enabled", True)
    ctx.core.config.set("notifications.push_enabled", True)
    done = {item["id"]: item["done"] for item in status(ctx)["items"]}
    assert done["alerts_on"] is False


async def test_checklist_can_be_dismissed_per_server(core):
    survival, creative = core.servers["survival"], core.servers["creative"]
    assert dismiss(survival)["show"] is False
    assert status(creative)["show"] is True


# ------------------------------------------------------------------- the API
def test_the_new_pages_are_served_per_server(multi_client):
    for path in ("chat", "world/timeline", "getting-started"):
        assert multi_client.get(f"/api/servers/creative/{path}").status_code == 200, path


def test_chat_over_the_api_refuses_what_it_should(multi_client):
    answer = multi_client.post("/api/servers/creative/chat", json={"message": "stop\nop Alex"})
    assert answer.status_code == 400
    assert "letters" in answer.json()["detail"]
    # The server is off, so even a fine message cannot be sent.
    offline = multi_client.post("/api/servers/creative/chat", json={"message": "hello"})
    assert offline.status_code == 400
    assert "running" in offline.json()["detail"]


def test_undo_over_the_api_needs_the_confirmation(multi_client):
    answer = multi_client.post(
        "/api/servers/creative/world/undo", json={"backup_id": 1, "confirm": False}
    )
    assert answer.status_code == 400


def test_autosleep_settings_are_saved_and_checked(multi_client):
    url = "/api/servers/creative/settings"
    saved = multi_client.put(
        url, json={"updates": {"server.autosleep": True, "server.autosleep_minutes": 45}}
    ).json()
    assert saved["rejected"] == {}
    assert multi_client.get("/api/servers/creative/status").json()["autosleep"] is True

    for bad in (0, -5, 4000):
        rejected = multi_client.put(url, json={"updates": {"server.autosleep_minutes": bad}}).json()
        assert "server.autosleep_minutes" in rejected["rejected"]
    # One server's setting is its own.
    assert multi_client.get("/api/servers/survival/status").json()["autosleep"] is False


def test_the_checklist_can_be_dismissed_over_the_api(multi_client):
    url = "/api/servers/creative/getting-started"
    assert multi_client.get(url).json()["show"] is True
    assert multi_client.post(f"{url}/dismiss").json()["show"] is False
    assert multi_client.get(url).json()["show"] is False


# ---------------------------------------------- console formats and fakes
@pytest.mark.parametrize(
    "raw",
    [
        "[12:00:00] [Server thread/INFO]: <Alex> hi there",
        "[12:00:00] [Server thread/INFO] (Minecraft) <Alex> hi there",
        "[12:00:00] [Server thread/INFO] [minecraft/MinecraftServer]: <Alex> hi there",
        "[12:00:00 INFO]: <Alex> hi there",
        "[12:00:00] [Async Chat Thread - #0/INFO]: <Alex> hi there",
        "\x1b[0;37m[12:00:00 INFO]: <Alex> hi there\x1b[m",
    ],
)
def test_chat_is_read_from_every_server_types_console(raw):
    """Vanilla, Fabric, Forge/NeoForge and Paper/Purpur print their consoles
    differently; chat must be found in all of them."""
    from agent.minecraft.console import parse_line

    assert parse_chat(parse_line(raw, 1)) == ("player", "Alex", "hi there")


@pytest.mark.parametrize(
    "raw,joined,left",
    [
        ("[12:00:00 INFO]: Steve joined the game", "Steve", None),
        (
            "[12:00:00] [Server thread/INFO] [minecraft/MinecraftServer]: Steve left the game",
            None,
            "Steve",
        ),
        (
            "[12:00:00] [Server thread/INFO]: Steve (formerly known as Bob) joined the game",
            "Steve",
            None,
        ),
        # Typed in chat: not a join or a leave.
        ("[12:00:00] [Server thread/INFO]: <Bob> Steve joined the game", None, None),
        ("[12:00:00 INFO]: <Bob> Steve left the game", None, None),
    ],
)
def test_joins_and_leaves_are_only_the_servers_own_lines(raw, joined, left):
    from agent.minecraft.console import extract_signals, parse_line

    sig = extract_signals(parse_line(raw, 1))
    assert sig.player_joined == joined
    assert sig.player_left == left


def test_a_player_cannot_fake_the_player_list():
    from agent.minecraft.console import extract_signals, parse_line

    fake = "[12:00:00] [Server thread/INFO]: <Bob> There are 0 of a max of 20 players online:"
    assert extract_signals(parse_line(fake, 1)).player_list is None
    real = "[12:00:00 INFO]: There are 1 of a max of 20 players online: Bob"
    assert extract_signals(parse_line(real, 1)).player_list == (1, 20, ["Bob"])
