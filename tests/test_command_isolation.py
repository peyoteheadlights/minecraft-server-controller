"""Command-execution isolation, and mod behaviour verified against a
running server rather than asserted from filenames.
"""

import inspect
import os
import re
from pathlib import Path

import pytest

from agent.database.db import Database
from agent.events import EventBus
from agent.minecraft.commands import CommandError, validate
from agent.minecraft.process import MinecraftServer, ServerError
from agent.mods.manager import ModManager

from .test_mods import make_jar

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
INSTALLER_DIR = Path(__file__).resolve().parent.parent / "installer"


# ====================================================================
# 1. No path from the API to a Windows shell
# ====================================================================
def python_sources():
    return list(AGENT_DIR.rglob("*.py")) + list(INSTALLER_DIR.rglob("*.py"))


def test_no_shell_execution_anywhere_in_the_agent():
    """shell=True, os.system and friends must not exist in the codebase."""
    forbidden = re.compile(r"shell\s*=\s*True|os\.system\(|os\.popen\(|commands\.getoutput")
    offenders = []
    for path in python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "shell execution found: " + "; ".join(offenders)


def test_no_dynamic_code_execution():
    forbidden = re.compile(r"\beval\s*\(|\bexec\s*\(|__import__\s*\(|pickle\.loads?\(")
    offenders = []
    for path in python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line) and "create_subprocess_exec" not in line:
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "dynamic execution found: " + "; ".join(offenders)


def test_every_subprocess_call_uses_an_argument_list():
    """A string command line can be re-parsed by a shell; a list cannot."""
    pattern = re.compile(r"(subprocess\.(run|Popen|call)|create_subprocess_exec)\s*\(\s*(.)")
    for path in python_sources():
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            following = match.group(3)
            assert following in "[*(", (
                f"{path.name}: subprocess call does not start with a list or unpacked list: "
                f"{text[match.start():match.start() + 90]}"
            )


def test_the_api_exposes_no_general_execution_endpoint():
    """Only the predefined operations exist. There is no /execute."""
    from agent.api import routes

    source = inspect.getsource(routes)
    for forbidden in ("/execute", "/shell", "/run", "/cmd", "/powershell", "/system"):
        assert f'"{forbidden}"' not in source, f"an execution-style route exists: {forbidden}"
    # the one place free text reaches the OS is the Minecraft console, and it
    # goes to that process's stdin
    assert "core.server.send_command(validated.raw)" in source


def test_minecraft_commands_only_reach_process_stdin():
    """send_command writes to stdin and does nothing else."""
    source = inspect.getsource(MinecraftServer.send_command)
    assert "self.process.stdin.write" in source
    for forbidden in ("subprocess", "os.system", "shell", "Popen"):
        assert forbidden not in source


@pytest.mark.parametrize("payload", [
    "say hi & calc.exe",
    "say hi | powershell",
    "say hi; shutdown /s /t 0",
    "say hi && del C:\\Windows",
    "say $(rm -rf /)",
    "say `whoami`",
    "say hi\nstop",
    "say hi\r\nop attacker",
    "say hi\x00stop",
    "cmd.exe /c calc",
    "../../../windows/system32/cmd.exe",
    "say hi > C:\\evil.txt",
    "say hi < input.txt",
])
def test_os_command_shapes_are_rejected_by_validation(payload):
    with pytest.raises(CommandError):
        validate(payload, confirm=True)


def test_a_bare_program_name_is_treated_as_a_minecraft_command_not_a_program():
    """'powershell -c calc' looks like a valid Minecraft command name, so it is
    accepted as text - and text only ever reaches Minecraft's stdin, where the
    server answers 'Unknown command'. Nothing executes it."""
    result = validate("powershell -c calc")
    assert result.name == "powershell"
    assert result.raw == "powershell -c calc"
    # proof it goes nowhere else: the only consumer is the stdin writer
    source = inspect.getsource(MinecraftServer.send_command)
    assert "stdin.write" in source and "subprocess" not in source


async def test_newline_cannot_smuggle_a_second_command_into_stdin(config):
    """Even if validation were bypassed, the writer refuses multi-line input."""
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=20)
    try:
        with pytest.raises(ServerError, match="single line"):
            await server.send_command("say hello\nstop")
        assert server.state.value == "ONLINE", "the server must still be running"
    finally:
        await server.stop()


def test_launch_arguments_come_only_from_configuration(config):
    """Nothing an API caller controls can enter the launch command."""
    bus = EventBus()
    server = MinecraftServer(config, bus)
    command = server.build_command()
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    from agent.api.routes import SETTABLE_PREFIXES
    for editable in SETTABLE_PREFIXES:
        assert not editable.startswith("server.raw_command")
        assert editable not in ("server.java", "server.jar", "server.directory")


# ====================================================================
# 2. Mod disable / enable verified against a running server
# ====================================================================
@pytest.fixture
def mod_setup(config):
    bus = EventBus()
    db = Database(config.database_path)
    db.register_server("test", "Test", str(config.server_dir))
    server = MinecraftServer(config, bus, db)
    server.mc_version = "1.21.1"
    return config, server, ModManager(config, bus, db, server)


def loaded_mods(server) -> list[str]:
    """Read the mods the server actually reported loading."""
    names = []
    collecting = False
    for line in server.console.tail(200):
        if "Loading" in line.raw and "mods:" in line.raw:
            collecting = True
            continue
        if collecting:
            if "- " in line.raw:
                names.append(line.raw.split("- ", 1)[1].strip())
            else:
                break
    return names


async def test_disabled_mod_is_not_loaded_by_the_server(mod_setup):
    """Enable -> start -> loaded. Disable -> start -> not loaded."""
    config, server, mods = mod_setup
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0")

    await server.start()
    assert await server.wait_online(timeout=20)
    assert "cooltech" in loaded_mods(server), "the enabled mod should be loaded"
    await server.stop()

    await mods.set_enabled("cooltech.jar", False, user="tester")
    assert (config.mods_dir / "cooltech.jar.disabled").is_file()
    server.console.clear()

    await server.start()
    assert await server.wait_online(timeout=20)
    assert "cooltech" not in loaded_mods(server), "a disabled mod must not be loaded"
    await server.stop()

    await mods.set_enabled("cooltech.jar.disabled", True, user="tester")
    server.console.clear()
    await server.start()
    assert await server.wait_online(timeout=20)
    assert "cooltech" in loaded_mods(server), "re-enabling must restore loading"
    await server.stop()


async def test_rollback_after_a_failed_startup_restores_a_working_server(mod_setup):
    """The full recovery path: update -> startup fails -> roll back -> online."""
    config, server, mods = mod_setup
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "1.0.0")

    # working baseline
    await server.start()
    assert await server.wait_online(timeout=20)
    await server.stop()

    # archive the good version, then "update" to a bad one
    good = mods.find("cooltech.jar")
    archive = mods.archive(config.mods_dir / "cooltech.jar", good, source="pre-update")
    (config.mods_dir / "cooltech.jar").unlink()
    make_jar(config.mods_dir / "cooltech.jar", "cooltech", "2.0.0-broken")
    assert mods.find_by_id("cooltech").version == "2.0.0-broken"

    # the new version breaks startup
    os.environ["FAKE_MIXIN_CRASH"] = "1"
    try:
        await server.start()
        assert not await server.wait_online(timeout=6)
        assert await server.wait_exit(timeout=15)
        assert server.state.value == "CRASHED"
        assert server.last_exit_reason.value == "startup_failure"
    finally:
        os.environ.pop("FAKE_MIXIN_CRASH", None)

    # roll back and confirm the server actually comes up again
    result = await mods.rollback("cooltech", str(archive), user="tester")
    assert result["restored"]["version"] == "1.0.0"
    server.console.clear()
    await server.start()
    assert await server.wait_online(timeout=20), "the server must be online after rollback"
    assert "cooltech" in loaded_mods(server)
    await server.stop()


async def test_user_restarts_do_not_count_towards_the_crash_limit(config):
    """Crash-loop protection must not be tripped by ordinary restarts."""
    bus = EventBus()
    server = MinecraftServer(config, bus)
    await server.start()
    await server.wait_online(timeout=20)
    for _ in range(4):
        await server.restart(actor="tester")
        assert await server.wait_online(timeout=20)
    assert server.recent_crash_count() == 0
    assert server.auto_restart_blocked is False
    await server.stop()


async def test_five_crashes_stop_automatic_restarts(make_config):
    config = make_config(**{
        "monitor.auto_restart": True,
        "monitor.restart_delay": 0.05,
        "monitor.max_crashes": 5,
        "monitor.crash_window_minutes": 10,
    })
    bus = EventBus()
    events = []
    bus.subscribe(lambda event: events.append(event.type))
    server = MinecraftServer(config, bus)
    os.environ["FAKE_CRASH_ON_START"] = "1"
    try:
        await server.start()
        for _ in range(400):
            await __import__("asyncio").sleep(0.05)
            if server.auto_restart_blocked:
                break
        assert server.auto_restart_blocked is True
        assert server.recent_crash_count() >= 5
        assert "crash_loop" in events
        # and it stays stopped rather than trying again
        assert events.count("crash_loop") >= 1
    finally:
        os.environ.pop("FAKE_CRASH_ON_START", None)
