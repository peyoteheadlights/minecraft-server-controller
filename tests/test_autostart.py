"""Windows startup: task definition, read-back, conflict handling, and the
startup diagnostics that explain what happened when nobody was watching.

Task Scheduler itself only exists on Windows, so the Windows calls are faked
at the single point where they happen (run_tool). Everything else - the XML
that gets registered, how it is parsed back, how mismatches are detected,
what gets logged - is the real code.
"""

import json
import sys
from pathlib import Path

import pytest

from agent import startup_diag
from installer import autostart

PROJECT = Path(__file__).resolve().parent.parent
PY = r"C:\Users\Alex\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
WORKDIR = r"C:\path\to\minecraft-server-control"
ARGS = "-m agent.main --launched-by task"


# ================================================================ the task XML
def parsed(mode="boot", user=r"HOST-PC\Alex", command=PY, workdir=WORKDIR):
    return autostart.parse_task_xml(
        autostart.build_task_xml(mode, user, command, ARGS, workdir,
                                 start_boundary="2026-09-21T00:00:00"))


def test_boot_task_runs_the_exact_command_from_the_project_folder():
    task = parsed()
    assert task["command"] == PY
    assert task["arguments"] == ARGS
    assert task["working_directory"] == WORKDIR


def test_boot_task_runs_without_login_as_the_user_with_least_privilege():
    task = parsed()
    assert task["mode"] == "boot"
    assert task["logon_type"] == "S4U", "S4U runs at boot without storing a password"
    assert task["user"] == r"HOST-PC\Alex"
    assert task["run_level"] == "LeastPrivilege", "the agent must not run as Administrator"


def test_logon_task_runs_in_the_users_session():
    task = parsed("logon")
    assert task["mode"] == "logon"
    assert task["logon_type"] == "InteractiveToken"
    logon = [t for t in task["triggers"] if t["type"] == "LogonTrigger"]
    assert logon and logon[0]["enabled"]


def test_task_is_kept_alive_without_duplicates():
    task = parsed()
    kinds = {t["type"]: t for t in task["triggers"]}
    assert "BootTrigger" in kinds
    assert kinds["BootTrigger"]["delay"] == "PT30S"
    assert kinds["TimeTrigger"]["repeat_every"] == "PT5M"
    assert task["multiple_instances"] == "IgnoreNew", \
        "the repeating trigger must never start a second copy"


def test_task_is_never_killed_by_windows_defaults():
    task = parsed()
    assert task["execution_time_limit"] == "PT0S", "the default 72-hour limit would kill the agent"
    assert task["stops_on_battery"] is False
    assert task["enabled"] is True


def test_special_characters_survive_the_round_trip():
    user = r"DOMAIN\O'Brien & Sons"
    command = r"C:\Program Files\Py <3>\pythonw.exe"
    workdir = r"C:\Games & Mods\minecraft-server-control"
    task = parsed(user=user, command=command, workdir=workdir)
    assert task["user"] == user
    assert task["command"] == command
    assert task["working_directory"] == workdir


def test_relative_paths_are_refused():
    with pytest.raises(autostart.AutostartError, match="absolute"):
        autostart.build_task_xml("boot", "u", "pythonw.exe", ARGS, WORKDIR)
    with pytest.raises(autostart.AutostartError, match="absolute"):
        autostart.build_task_xml("boot", "u", PY, ARGS, r".\minecraft-server-control")


def test_task_xml_can_be_written_as_utf16_like_schtasks_expects(tmp_path):
    xml = autostart.build_task_xml("boot", "u", PY, ARGS, WORKDIR)
    target = tmp_path / "task.xml"
    target.write_text(xml, encoding="utf-16")
    assert target.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff"), "UTF-16 with a byte-order mark"
    assert autostart.parse_task_xml(target.read_text(encoding="utf-16"))["command"] == PY


# ================================================================ read-back checks
def test_matching_registration_has_no_problems():
    expected = {"command": PY, "arguments": ARGS, "working_directory": WORKDIR}
    assert autostart.compare_to_expected(parsed(), expected) == []


def test_wrong_working_directory_is_reported():
    expected = {"command": PY, "arguments": ARGS, "working_directory": r"C:\elsewhere"}
    problems = autostart.compare_to_expected(parsed(), expected)
    assert any("starts in" in p for p in problems)


def test_a_task_pointing_at_another_python_is_reported():
    expected = {"command": r"C:\Python312\pythonw.exe", "arguments": ARGS, "working_directory": WORKDIR}
    problems = autostart.compare_to_expected(parsed(), expected)
    assert any("interpreter" in p for p in problems)


def test_a_time_limited_task_is_reported():
    registered = dict(parsed(), execution_time_limit="PT72H")
    expected = {"command": PY, "arguments": ARGS, "working_directory": WORKDIR}
    assert any("time limit" in p for p in autostart.compare_to_expected(registered, expected))


def test_expected_launch_uses_absolute_pythonw(tmp_path):
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")
    launch = autostart.expected_launch(str(tmp_path / "python.exe"))
    assert launch["command"] == str((tmp_path / "pythonw.exe").resolve())
    assert Path(launch["working_directory"]) == PROJECT
    assert launch["arguments"] == ARGS


def test_expected_launch_falls_back_to_python_when_pythonw_is_missing(tmp_path):
    (tmp_path / "python.exe").write_bytes(b"")
    assert autostart.expected_launch(str(tmp_path / "python.exe"))["command"] == \
        str((tmp_path / "python.exe").resolve())


def test_store_python_is_refused():
    problems = autostart.interpreter_problems(
        r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python.exe")
    assert any("Store" in p for p in problems)


def test_task_runtime_fields_are_parsed_and_unknown_when_absent(monkeypatch):
    sample = ("Folder: \\\nHostName: HOST-PC\nTaskName: \\Minecraft Server Control\n"
              "Next Run Time: 21/09/2026 12:05:00\nStatus: Running\n"
              "Last Run Time: 21/09/2026 12:00:31\nLast Result: 267009\n")
    monkeypatch.setattr(autostart, "run_tool", lambda args, timeout=60: (0, sample, ""))
    info = autostart.task_runtime()
    assert info["status"] == "Running"
    assert info["last_result"].startswith("267009")
    monkeypatch.setattr(autostart, "run_tool", lambda args, timeout=60: (1, "", "not found"))
    assert autostart.task_runtime() == {"status": None, "last_run_time": None,
                                        "last_result": None, "next_run_time": None}


def test_report_is_explicit_about_being_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    data = autostart.report()
    assert data["verdict"] == "unsupported"
    assert data["registered"] is None, "not checked is not the same as not registered"


# ================================================================ enable / disable
class FakeWindows:
    """Stands in for schtasks.exe and sc.exe, recording every call."""

    def __init__(self, legacy_service=False):
        self.calls = []
        self.task_xml = None
        self.legacy = legacy_service

    def __call__(self, args, timeout=60):
        assert isinstance(args, list), "Windows tools must be called with an argument list"
        self.calls.append(args)
        tool = args[0].lower()
        if tool == "schtasks.exe" and "/Create" in args:
            assert "/F" in args, "re-registering must replace, never duplicate"
            self.task_xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            return 0, "SUCCESS", ""
        if tool == "schtasks.exe" and "/XML" in args:
            return (0, self.task_xml, "") if self.task_xml else (1, "", "cannot find the file")
        if tool == "schtasks.exe" and "/Delete" in args:
            self.task_xml = None
            return 0, "SUCCESS", ""
        if tool == "schtasks.exe":
            return (0, "Status: Ready\n", "") if self.task_xml else (1, "", "not found")
        if tool == "sc.exe" and args[1] == "query":
            return (0, "SERVICE_NAME: MinecraftServerControl\n STATE : 1 STOPPED\n", "") \
                if self.legacy else (1060, "", "does not exist")
        if tool == "sc.exe" and args[1] == "delete":
            self.legacy = False
            return 0, "[SC] DeleteService SUCCESS", ""
        return 0, "", ""


@pytest.fixture
def windows(monkeypatch, tmp_path):
    fake = FakeWindows()
    monkeypatch.setattr(autostart, "IS_WINDOWS", True)
    monkeypatch.setattr(autostart, "run_tool", fake)
    monkeypatch.setattr(autostart, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "other_startup_entries", lambda: [])
    monkeypatch.setenv("USERDOMAIN", "HOST-PC")
    monkeypatch.setenv("USERNAME", "Alex")
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")
    fake.exe = str(tmp_path / "python.exe")
    return fake


def test_enable_registers_and_verifies_by_reading_back(windows):
    result = autostart.enable("boot", pin_java=False, executable=windows.exe)
    assert result["registered"]["command"].endswith("pythonw.exe")
    assert result["registered"]["working_directory"] == str(PROJECT)
    assert result["registered"]["user"] == r"HOST-PC\Alex"
    create = [c for c in windows.calls if "/Create" in c][0]
    assert create[:3] == ["schtasks.exe", "/Create", "/TN"]


def test_enabling_twice_does_not_create_a_duplicate(windows):
    autostart.enable("boot", pin_java=False, executable=windows.exe)
    autostart.enable("logon", pin_java=False, executable=windows.exe)
    creates = [c for c in windows.calls if "/Create" in c]
    assert len(creates) == 2 and all("/F" in c for c in creates)
    assert autostart.parse_task_xml(windows.task_xml)["mode"] == "logon"


def test_enable_removes_the_broken_legacy_service(windows):
    windows.legacy = True
    result = autostart.enable("boot", pin_java=False, executable=windows.exe)
    assert ["sc.exe", "delete", autostart.LEGACY_SERVICE] in windows.calls
    assert any("Removed the old Windows Service" in a for a in result["actions"])


def test_boot_mode_requires_administrator(windows, monkeypatch):
    monkeypatch.setattr(autostart, "is_admin", lambda: False)
    with pytest.raises(autostart.AutostartError, match="Administrator"):
        autostart.enable("boot", pin_java=False, executable=windows.exe)


def test_disable_removes_the_task(windows):
    autostart.enable("boot", pin_java=False, executable=windows.exe)
    assert autostart.disable()["removed"] is True
    assert windows.task_xml is None
    assert autostart.disable()["removed"] is False, "disabling twice is harmless"


def test_report_after_enable_says_registered_correctly(windows, monkeypatch):
    autostart.enable("boot", pin_java=False, executable=windows.exe)
    monkeypatch.setattr(autostart, "legacy_service",
                        lambda: {"exists": False, "state": None, "python_class": None,
                                 "python_class_valid": None})
    data = autostart.report(executable=windows.exe)
    assert data["registered"] is True
    assert data["mechanism"] == "Task Scheduler"
    assert data["points_to_current_app"] is True
    assert data["verdict"] == "registered correctly", data["problems"]


def test_report_flags_the_broken_legacy_service(windows, monkeypatch):
    monkeypatch.setattr(autostart, "legacy_service",
                        lambda: {"exists": True, "state": "1 STOPPED",
                                 "python_class": "__main__.MinecraftControlService",
                                 "python_class_valid": False})
    data = autostart.report(executable=windows.exe)
    assert data["registered"] is False
    assert data["mechanism"] == "Windows Service (legacy)"
    assert any("__main__.MinecraftControlService" in p for p in data["problems"])


def test_pin_java_replaces_a_bare_name_with_an_absolute_path(tmp_path, monkeypatch):
    from agent.config import DEFAULTS, Config, _deep_merge
    cfg_path = tmp_path / "config.yaml"
    Config(_deep_merge(DEFAULTS, {"server": {"java": "java", "raw_command": None}}), cfg_path).save()
    fake_java = tmp_path / "bin" / "java"
    fake_java.parent.mkdir()
    fake_java.write_text("")
    monkeypatch.setattr("shutil.which", lambda name: str(fake_java))
    pinned = autostart.pin_java_path(cfg_path)
    assert pinned == str(fake_java.resolve())
    assert Config.load(cfg_path).get("server.java") == str(fake_java.resolve())
    assert autostart.pin_java_path(cfg_path) is None, "already absolute: nothing to change"


# ================================================================ diagnostics
def test_startup_log_records_each_stage_with_timestamps(isolated_startup_log):
    startup_diag.begin(["agent.main", "--launched-by", "task"], "task")
    startup_diag.record("config_loaded", source="x")
    startup_diag.record("controller_initialized", ok=True)
    startup_diag.finish("stopped", exit_code=0)
    events = [json.loads(line) for line in
              (isolated_startup_log / "startup.log").read_text().splitlines()]
    assert [e["event"] for e in events] == ["process_started", "config_loaded",
                                            "controller_initialized", "process_finished"]
    assert all("ts" in e and "pid" in e for e in events)
    first = events[0]
    assert first["launched_by"] == "task"
    assert first["executable"] == sys.executable
    assert "cwd" in first and "argv" in first
    last = startup_diag.read_last()
    assert last["outcome"] == "stopped"


def test_a_closed_startup_record_is_not_rewritten(isolated_startup_log):
    startup_diag.begin(["agent.main"], "manual")
    startup_diag.finish("failed", exit_code=2)
    startup_diag.record("controller_initialized")
    assert startup_diag.read_last()["last_event"] == "process_finished"
    assert startup_diag.read_last()["outcome"] == "failed"


def test_exceptions_are_recorded_with_a_traceback(isolated_startup_log):
    startup_diag.begin(["agent.main"], "task")
    try:
        raise ValueError("boom")
    except ValueError as exc:
        startup_diag.record_exception("main", exc)
    entry = startup_diag.tail(1)[0]
    assert entry["event"] == "exception"
    assert "ValueError: boom" in entry["error"]
    assert "Traceback" in entry["traceback"]


def test_missing_console_streams_are_redirected_to_a_file(isolated_startup_log, monkeypatch):
    """pythonw.exe starts with sys.stdout and sys.stderr set to None."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert startup_diag.attach_streams_if_missing() is True
    print("written with no console")
    sys.stdout.flush()
    assert "written with no console" in (isolated_startup_log / "console.log").read_text()


def test_main_logs_a_refused_start_so_it_can_be_diagnosed(config, isolated_startup_log,
                                                           monkeypatch, tmp_path):
    from agent.main import main
    from agent.security.auth import hash_password
    cfg = tmp_path / "config.yaml"
    config.set("tls.enabled", False)
    config.set("network.host", "100.101.102.103")
    config.save(cfg)
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password("long enough password", rounds=1000))
    assert main(["--config", str(cfg), "--no-tls", "--launched-by", "task"]) == 2
    events = [e["event"] for e in startup_diag.tail(20)]
    assert events[0] == "process_started"
    assert "config_loaded" in events
    last = startup_diag.read_last()
    assert last["launched_by"] == "task"
    assert last["outcome"] == "failed"


def test_bind_wait_returns_at_once_for_loopback(isolated_startup_log):
    from agent.main import wait_for_bind_address
    assert wait_for_bind_address("127.0.0.1", timeout=0) is True
    assert startup_diag.tail(5) == []


def test_bind_wait_retries_then_reports_an_address_that_never_appears(isolated_startup_log):
    """The boot race: the Tailscale address is not assigned yet. 203.0.113.0/24
    is a documentation range, never assigned to a local interface."""
    from agent.main import wait_for_bind_address
    assert wait_for_bind_address("203.0.113.77", timeout=0.6, interval=0.1) is False
    events = [e["event"] for e in startup_diag.tail(20)]
    assert "bind_address_waiting" in events
    assert events[-1] == "bind_address_gave_up"


# ================================================================ Windows' exported XML
def windows_export(*drop):
    """Our task XML as Windows exports it: elements equal to the Task Scheduler
    default are left out. Found by the live Windows CI run, where RunLevel came
    back missing."""
    xml = autostart.build_task_xml("boot", r"HOST-PC\Alex", PY, ARGS, WORKDIR,
                                   start_boundary="2026-09-21T00:00:00")
    for element in ("RunLevel", "MultipleInstancesPolicy", *drop):
        start = xml.index(f"<{element}>")
        end = xml.index(f"</{element}>") + len(f"</{element}>")
        xml = xml[:start] + xml[end:]
    return xml


def test_omitted_defaults_are_read_as_the_defaults():
    task = autostart.parse_task_xml(windows_export())
    assert task["run_level"] == "LeastPrivilege"
    assert task["multiple_instances"] == "IgnoreNew"
    expected = {"command": PY, "arguments": ARGS, "working_directory": WORKDIR}
    assert autostart.compare_to_expected(task, expected) == []


def test_an_omitted_time_limit_means_72_hours_and_is_reported():
    """No ExecutionTimeLimit means Windows' default, which would kill the
    agent after three days. It must not be treated as "no limit"."""
    task = autostart.parse_task_xml(windows_export("ExecutionTimeLimit"))
    assert task["execution_time_limit"] == "PT72H"
    expected = {"command": PY, "arguments": ARGS, "working_directory": WORKDIR}
    assert any("time limit" in p for p in autostart.compare_to_expected(task, expected))
