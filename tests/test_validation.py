import pytest

from agent.minecraft.analyzer import analyze
from agent.minecraft.commands import CommandError, describe_danger, validate
from agent.scheduler.scheduler import ScheduleError, next_run
from agent.security.paths import PathSafetyError, is_inside, safe_filename, safe_join


# ---------------------------------------------------------------- commands
def test_plain_command_is_accepted():
    result = validate("say hello everyone")
    assert result.name == "say"
    assert result.dangerous is False


def test_leading_slash_is_stripped():
    assert validate("/whitelist list", confirm=True).raw == "whitelist list"


@pytest.mark.parametrize(
    "bad",
    [
        "say hi\nstop",  # newline injection: two commands in one
        "say hi; shutdown -s",  # shell separator
        "say `whoami`",  # backtick
        "say $(rm -rf /)",  # command substitution
        "say a && del C:\\",  # chained shell command
        "",  # empty
        "   ",  # whitespace only
        "1say hi",  # command name must start with a letter
        "x" * 600,  # too long
    ],
)
def test_dangerous_shapes_are_refused(bad):
    with pytest.raises(CommandError):
        validate(bad)


@pytest.mark.parametrize(
    "command", ["stop", "ban Steve", "op Steve", "whitelist off", "deop Steve", "ban-ip 1.2.3.4"]
)
def test_dangerous_commands_need_confirmation(command):
    with pytest.raises(CommandError):
        validate(command)
    validated = validate(command, confirm=True)
    assert validated.dangerous is True
    assert validated.danger_reason
    assert describe_danger(command)


def test_selector_and_json_syntax_survives_validation():
    validated = validate('tellraw @a {"text":"hi","color":"gold"}')
    assert validated.name == "tellraw"


# ---------------------------------------------------------------- analyzer
def test_out_of_memory_is_identified_with_evidence():
    lines = [
        "[12:00:00] [Server thread/INFO]: Preparing spawn area: 84%",
        "[12:00:05] [Server thread/ERROR]: java.lang.OutOfMemoryError: Java heap space",
        "\tat net.minecraft.server.MinecraftServer.tick(MinecraftServer.java:801)",
    ]
    result = analyze(lines, exit_code=1)
    assert result.category == "OutOfMemoryError"
    # The error itself is in the log, so this one is confirmed rather than
    # merely likely - the distinction is the point of the confidence field.
    assert result.confidence == "confirmed"
    assert "certain" in result.evidence_basis
    assert any("OutOfMemoryError" in line for line in result.evidence)
    assert "Xmx" in result.advice


def test_missing_dependency_is_identified_and_names_the_mod():
    lines = [
        "[12:00:01] [main/ERROR]: Incompatible mods found!",
        "[12:00:01] [main/ERROR]: Mod 'sodium' requires any version of fabric-api, which is missing!",
    ]
    result = analyze(lines, exit_code=1, known_mod_ids=["sodium", "fabric-api"])
    assert result.category in ("ModDependencyError", "IncompatibleMod")
    assert "sodium" in result.suspect_mods


def test_mixin_failure_is_identified():
    lines = [
        "[12:00:02] [main/ERROR]: Mixin apply for mod iris failed",
        "org.spongepowered.asm.mixin.injection.throwables.InjectionError: boom",
    ]
    result = analyze(lines, exit_code=1)
    assert result.category == "MixinError"
    assert result.exception


def test_port_conflict_and_eula_are_identified():
    assert (
        analyze(["[12:00:00] [Server thread/WARN]: FAILED TO BIND TO PORT!"]).category
        == "PortInUse"
    )
    assert (
        analyze(["You need to agree to the EULA in order to run the server."]).category
        == "EulaNotAccepted"
    )


def test_unknown_crash_admits_it_does_not_know():
    result = analyze(["[12:00:00] [Server thread/INFO]: nothing interesting here"], exit_code=1)
    assert result.category == "Unknown"
    assert result.confidence == "unknown"
    assert "could not be determined" in result.summary


def test_java_version_mismatch_is_identified():
    lines = [
        "java.lang.UnsupportedClassVersionError: net/minecraft/Main has been compiled by a "
        "more recent version of the Java Runtime (class file version 65.0)"
    ]
    result = analyze(lines, exit_code=1)
    assert result.category == "JavaVersionIncompatible"
    assert "Java 21" in result.advice


# ---------------------------------------------------------------- paths
@pytest.mark.parametrize(
    "bad",
    [
        "../evil.jar",
        "..\\evil.jar",
        "mods/../../evil.jar",
        "sub/dir.jar",
        "mod.exe",
        "mod.bat",
        "mod.ps1",
        "script.py",
        "CON.jar",
        "",
        ".",
        "..",
        "trailing.jar ",
        "nul.jar",
    ],
)
def test_unsafe_filenames_are_refused(bad):
    with pytest.raises(PathSafetyError):
        safe_filename(bad, {".jar"})


def test_safe_filenames_are_accepted():
    for name in ["sodium-fabric-0.5.8.jar", "fabric-api-0.92.0+1.20.1.jar", "Mod (1).jar"]:
        assert safe_filename(name, {".jar"}) == name


def test_safe_join_keeps_files_inside_the_base(tmp_path):
    base = tmp_path / "mods"
    base.mkdir()
    assert safe_join(base, "ok.jar", allowed_extensions={".jar"}).parent == base
    with pytest.raises(PathSafetyError):
        safe_join(base, "../escape.jar", allowed_extensions={".jar"})


def test_is_inside_rejects_sibling_directories(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert is_inside(tmp_path / "a", tmp_path / "a" / "file")
    assert not is_inside(tmp_path / "a", tmp_path / "b" / "file")


def test_symlinked_jar_is_refused(tmp_path):
    from agent.security.paths import assert_not_symlink

    real = tmp_path / "real.jar"
    real.write_bytes(b"PK")
    link = tmp_path / "link.jar"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(PathSafetyError):
        assert_not_symlink(link)


# ---------------------------------------------------------------- scheduler
def test_daily_and_weekly_and_interval_parse():
    assert next_run("daily", "23:00") > 0
    assert next_run("weekly", "sun 04:00") > 0
    assert next_run("interval", "6h") > 0


def test_daily_schedule_is_always_in_the_future():
    import time

    assert next_run("daily", "00:01", after=time.time()) > time.time()


@pytest.mark.parametrize(
    "kind,expr",
    [
        ("daily", "25:00"),
        ("daily", "noon"),
        ("weekly", "funday 04:00"),
        ("interval", "5s"),
        ("interval", "soon"),
        ("yearly", "01:00"),
    ],
)
def test_bad_schedules_are_refused(kind, expr):
    with pytest.raises(ScheduleError):
        next_run(kind, expr)
