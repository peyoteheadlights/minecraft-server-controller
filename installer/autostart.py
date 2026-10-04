"""Start the agent automatically with Windows, using Task Scheduler.

    python -m installer.autostart enable            # start at boot, no login needed (default)
    python -m installer.autostart enable --logon    # start when you log in instead
    python -m installer.autostart disable           # remove the startup task
    python -m installer.autostart status            # short summary
    python -m installer.autostart test              # full "Test Windows Startup" report
    python -m installer.autostart run               # start the task now, as Windows would

Why Task Scheduler, and not a Windows Service
---------------------------------------------
The command proven to work on this PC is `python -m agent.main`. The task runs
exactly that, with the working directory set to the project folder. A pywin32
service instead runs the code inside pythonservice.exe as LocalSystem, with a
different interpreter host, different PATH and different profile. Setup still
removes the old "MinecraftServerControl" service once if an earlier version
left one behind (see remove_legacy_service).

How the task is built
---------------------
* Command     : <your Python folder>\\pythonw.exe (no console window)
* Arguments   : -m agent.main --launched-by task
* Start in    : the project folder (absolute, recorded at registration time)
* Account     : your own Windows account - the same Python install, the same
                files and the same permissions as a manual launch
* Boot mode   : "S4U" logon - runs at boot whether or not anyone logs in, and
                does not store your password
* Logon mode  : runs after you log in, in your desktop session
* Privileges  : least privilege. The agent does not run as Administrator.
* Keep-alive  : a second trigger fires every 5 minutes. Because the task is
                set to "do not start a new instance", this does nothing while
                the agent is running and restarts it if it ever stopped.
* Time limit  : none. (Task Scheduler's default kills tasks after 72 hours.)
* Batteries   : ignored, so a laptop on battery does not stop the server.

Nothing is registered with a shell: the task definition is written as XML and
handed to schtasks.exe as an argument list.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Any
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent import startup_diag  # noqa: E402
from agent.winproc import NO_WINDOW  # noqa: E402

# MCSC_TASK_NAME lets CI register a uniquely named task, isolated from a real one.
TASK_NAME = os.environ.get("MCSC_TASK_NAME") or "Minecraft Server Control"
LEGACY_SERVICE = "MinecraftServerControl"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
KEEPALIVE_MINUTES = 5
BOOT_DELAY = "PT30S"
MODES = ("boot", "logon")

IS_WINDOWS = os.name == "nt"


class AutostartError(RuntimeError):
    pass


# ======================================================================
# What the task should run
# ======================================================================
def interpreter_paths(executable: str | None = None) -> dict[str, str]:
    """The interpreter to register. Always the real, absolute file - never a
    launcher alias, and never a relative path."""
    exe = Path(executable or sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    return {
        "python": str(exe),
        "pythonw": str(pythonw) if pythonw.is_file() else "",
        "chosen": str(pythonw) if pythonw.is_file() else str(exe),
    }


def expected_launch(executable: str | None = None) -> dict[str, str]:
    paths = interpreter_paths(executable)
    return {
        "command": paths["chosen"],
        "arguments": "-m agent.main --launched-by task",
        "working_directory": str(PROJECT_ROOT),
    }


def interpreter_problems(executable: str | None = None) -> list[str]:
    """Reasons the current interpreter cannot be used by a startup task."""
    exe = str(Path(executable or sys.executable).resolve())
    problems = []
    if "WindowsApps" in exe:
        problems.append(
            f"Python is the Microsoft Store build ({exe}). Store apps cannot be launched by "
            "Task Scheduler at boot. Install Python from python.org and reinstall the "
            "requirements with that interpreter."
        )
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        problems.append(
            f"This interpreter is missing the agent's packages ({exc}). Run "
            f'"{exe}" -m pip install -r requirements.txt, then enable again.'
        )
    return problems


def current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    if not user:
        raise AutostartError("Could not determine the current Windows user name")
    return f"{domain}\\{user}" if domain else user


# ======================================================================
# Task XML
# ======================================================================
def build_task_xml(mode: str, user: str, command: str, arguments: str, working_directory: str,
                   keepalive_minutes: int = KEEPALIVE_MINUTES,
                   start_boundary: str | None = None) -> str:
    """The complete task definition.

    Element order follows what Task Scheduler itself exports, so the file is
    accepted by every Windows version that supports schema 1.2.
    """
    if mode not in MODES:
        raise AutostartError(f"mode must be one of {MODES}")
    for name, value in (("command", command), ("working directory", working_directory)):
        # Task paths are Windows paths. PureWindowsPath judges them correctly
        # on any OS; Path covers the native form as well.
        if not value or not (PureWindowsPath(value).is_absolute() or Path(value).is_absolute()):
            raise AutostartError(f"The {name} must be an absolute path, got: {value!r}")

    start_boundary = start_boundary or dt.datetime.now().replace(microsecond=0).isoformat()
    u = escape(user)

    if mode == "boot":
        startup_trigger = (
            "    <BootTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            f"      <Delay>{BOOT_DELAY}</Delay>\n"
            "    </BootTrigger>\n"
        )
        logon_type = "S4U"
        description = ("Starts the Minecraft Server Control agent when Windows boots, "
                       "without anyone needing to log in.")
    else:
        startup_trigger = (
            "    <LogonTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            f"      <UserId>{u}</UserId>\n"
            f"      <Delay>{BOOT_DELAY}</Delay>\n"
            "    </LogonTrigger>\n"
        )
        logon_type = "InteractiveToken"
        description = ("Starts the Minecraft Server Control agent when "
                       f"{user} logs in to Windows.")

    keepalive = (
        "    <TimeTrigger>\n"
        "      <Repetition>\n"
        f"        <Interval>PT{int(keepalive_minutes)}M</Interval>\n"
        "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
        "      </Repetition>\n"
        f"      <StartBoundary>{escape(start_boundary)}</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "    </TimeTrigger>\n"
    )

    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{TASK_NS}">\n'
        "  <RegistrationInfo>\n"
        f"    <Author>{u}</Author>\n"
        f"    <Description>{escape(description)} Registered by installer/autostart.py; "
        f"mode={mode}.</Description>\n"
        f"    <URI>\\{escape(TASK_NAME)}</URI>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        f"{startup_trigger}"
        f"{keepalive}"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{u}</UserId>\n"
        f"      <LogonType>{logon_type}</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <IdleSettings>\n"
        "      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
        "      <RestartOnIdle>false</RestartOnIdle>\n"
        "    </IdleSettings>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(command)}</Command>\n"
        f"      <Arguments>{escape(arguments)}</Arguments>\n"
        f"      <WorkingDirectory>{escape(working_directory)}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


# Task Scheduler schema defaults (Task Scheduler 1.2 schema). Windows omits
# these from exported XML, so they are what an absent element means.
TASK_DEFAULTS = {
    "run_level": "LeastPrivilege",
    "multiple_instances": "IgnoreNew",
    "execution_time_limit": "PT72H",   # the 72-hour limit this project turns off
}


def parse_task_xml(xml_text: str) -> dict[str, Any]:
    """Read back what is actually registered. Source of truth for the report."""
    text = xml_text.lstrip("\ufeff").strip()
    if text.startswith("<?xml"):
        text = text[text.index("?>") + 2:]
    root = ET.fromstring(text)
    ns = {"t": TASK_NS}

    def find(path: str) -> str | None:
        node = root.find(path, ns)
        return node.text.strip() if node is not None and node.text else None

    triggers = []
    trigger_root = root.find("t:Triggers", ns)
    if trigger_root is not None:
        for trig in trigger_root:
            kind = trig.tag.split("}")[-1]
            interval = trig.find("t:Repetition/t:Interval", ns)
            enabled = trig.find("t:Enabled", ns)
            triggers.append({
                "type": kind,
                "enabled": (enabled.text.strip().lower() != "false") if enabled is not None and enabled.text else True,
                "repeat_every": interval.text.strip() if interval is not None and interval.text else None,
                "delay": (trig.find("t:Delay", ns).text.strip()
                          if trig.find("t:Delay", ns) is not None and trig.find("t:Delay", ns).text else None),
            })

    logon_type = find("t:Principals/t:Principal/t:LogonType")
    mode = None
    if any(t["type"] == "BootTrigger" for t in triggers):
        mode = "boot"
    elif any(t["type"] == "LogonTrigger" for t in triggers):
        mode = "logon"
    enabled = find("t:Settings/t:Enabled")

    return {
        "command": find("t:Actions/t:Exec/t:Command"),
        "arguments": find("t:Actions/t:Exec/t:Arguments"),
        "working_directory": find("t:Actions/t:Exec/t:WorkingDirectory"),
        "user": find("t:Principals/t:Principal/t:UserId"),
        "logon_type": logon_type,
        # Windows leaves out any setting that equals the Task Scheduler schema
        # default when it exports a task, so an absent element means the
        # default applies - it does not mean "unknown".
        "run_level": find("t:Principals/t:Principal/t:RunLevel") or TASK_DEFAULTS["run_level"],
        "enabled": (enabled or "true").lower() != "false",
        "multiple_instances": (find("t:Settings/t:MultipleInstancesPolicy")
                               or TASK_DEFAULTS["multiple_instances"]),
        "execution_time_limit": (find("t:Settings/t:ExecutionTimeLimit")
                                 or TASK_DEFAULTS["execution_time_limit"]),
        "stops_on_battery": (find("t:Settings/t:StopIfGoingOnBatteries") or "true").lower() == "true",
        "mode": mode,
        "triggers": triggers,
    }


def compare_to_expected(registered: dict[str, Any], expected: dict[str, str]) -> list[str]:
    """Differences between the registered task and this installation."""

    def norm(value: str | None) -> str:
        return os.path.normcase(os.path.normpath(value)) if value else ""

    problems = []
    if norm(registered.get("command")) != norm(expected["command"]):
        problems.append(f"The task runs {registered.get('command')!r}, but this installation's "
                        f"interpreter is {expected['command']!r}")
    if (registered.get("arguments") or "").split()[:2] != ["-m", "agent.main"]:
        problems.append(f"The task arguments are {registered.get('arguments')!r}, "
                        "expected '-m agent.main --launched-by task'")
    if norm(registered.get("working_directory")) != norm(expected["working_directory"]):
        problems.append(f"The task starts in {registered.get('working_directory')!r}, but the "
                        f"project is at {expected['working_directory']!r}. "
                        "`-m agent.main` only works from the project folder.")
    if registered.get("execution_time_limit") != "PT0S":
        problems.append(f"The task has a time limit of {registered['execution_time_limit']}; "
                        "Windows will kill the agent when it is reached")
    if registered.get("stops_on_battery"):
        problems.append("The task stops when the PC switches to battery power")
    if registered.get("multiple_instances") != "IgnoreNew":
        problems.append(f"Multiple-instance policy is {registered['multiple_instances']}; "
                        "a second copy could start and fight over the port")
    if not registered.get("enabled"):
        problems.append("The task exists but is disabled")
    return problems


# ======================================================================
# Talking to Windows
# ======================================================================
def _decode(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    for encoding in ("utf-8", "mbcs" if IS_WINDOWS else "latin-1", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace")


def run_tool(args: list[str], timeout: float = 60) -> tuple[int, str, str]:
    """Run a Windows tool with an argument list. Never a shell.

    A string is refused outright: on Windows a string argument is handed to
    CreateProcess as a raw command line and re-parsed by the target program,
    which is exactly the kind of ambiguity an argument list avoids.
    """
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise TypeError("run_tool requires a list of strings")
    try:
        proc = subprocess.run([*args], capture_output=True, timeout=timeout,
                              creationflags=NO_WINDOW)
    except FileNotFoundError:
        return 127, "", f"{args[0]} was not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{args[0]} failed to run: {exc}"
    return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)


def is_admin() -> bool | None:
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def query_task() -> dict[str, Any] | None:
    code, out, err = run_tool(["schtasks.exe", "/Query", "/TN", TASK_NAME, "/XML"])
    if code != 0:
        return None
    try:
        return parse_task_xml(out)
    except ET.ParseError as exc:
        return {"parse_error": str(exc)}


def task_runtime() -> dict[str, Any]:
    """Last run time and result, as Task Scheduler reports them.

    The field names schtasks prints are translated on non-English Windows. If
    they cannot be recognised, the values are reported as unknown rather than
    guessed.
    """
    code, out, _ = run_tool(["schtasks.exe", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    info: dict[str, Any] = {"status": None, "last_run_time": None,
                            "last_result": None, "next_run_time": None}
    if code != 0:
        return info
    wanted = {"status": "status", "last run time": "last_run_time",
              "last result": "last_result", "next run time": "next_run_time"}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in wanted and info[wanted[key]] is None:
            info[wanted[key]] = value.strip()
    if info["last_result"] is not None:
        meanings = {"0": "0 (success)", "267009": "267009 (currently running)",
                    "267011": "267011 (has not run yet)", "1": "1 (the agent exited with an error)",
                    "2": "2 (the agent refused to start - see logs/startup.log)",
                    "3": "3 (the network address never became available)"}
        info["last_result"] = meanings.get(info["last_result"], info["last_result"])
    return info


def legacy_service() -> dict[str, Any]:
    """Look for the old pywin32 service, which would fight the task for
    the port."""
    result: dict[str, Any] = {"exists": False, "state": None,
                              "python_class": None, "python_class_valid": None}
    if not IS_WINDOWS:
        return result
    code, out, _ = run_tool(["sc.exe", "query", LEGACY_SERVICE])
    if code != 0 or "SERVICE_NAME" not in out.upper():
        return result
    result["exists"] = True
    for line in out.splitlines():
        if "STATE" in line.upper() and ":" in line:
            result["state"] = line.split(":", 1)[1].strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SYSTEM\CurrentControlSet\Services\{LEGACY_SERVICE}\PythonClass") as key:
            value, _ = winreg.QueryValueEx(key, "")
        result["python_class"] = value
        result["python_class_valid"] = not str(value).startswith("__main__.")
    except (OSError, ImportError):
        pass  # value stays None: reported as unknown, not as valid
    return result


def other_startup_entries() -> list[dict[str, str]]:
    """Registry Run keys and Startup-folder items that also launch the agent.
    Any of these would start a second copy."""
    found: list[dict[str, str]] = []
    if not IS_WINDOWS:
        return found
    markers = ("agent.main", "minecraft-server-control", "installer.service", "mcsc")
    try:
        import winreg
        for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(hive, path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        if any(m in str(value).lower() for m in markers):
                            found.append({"kind": "registry Run key",
                                          "location": f"{hive_name}\\{path}\\{name}",
                                          "value": str(value)})
                        index += 1
            except OSError:
                continue
    except ImportError:
        pass
    folders = [
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
        Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp",
    ]
    for folder in folders:
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if "minecraft" in item.name.lower() or "mcsc" in item.name.lower():
                found.append({"kind": "Startup folder item", "location": str(item),
                              "value": "(shortcut target not inspected)"})
    return found


# ======================================================================
# Operations
# ======================================================================
def _require_windows() -> None:
    if not IS_WINDOWS:
        raise AutostartError("Windows startup registration is only available on Windows")


def remove_legacy_service() -> dict[str, Any] | None:
    """Remove the old service. Returns what was removed, or None if there was
    nothing to remove - never None for "removed, details unknown"."""
    info = legacy_service()
    if not info["exists"]:
        return None
    run_tool(["sc.exe", "stop", LEGACY_SERVICE])
    code, out, err = run_tool(["sc.exe", "delete", LEGACY_SERVICE])
    if code != 0:
        raise AutostartError(f"The old service could not be removed: {(err or out).strip()}")
    startup_diag.append_event("setup.log", "legacy_service_removed", python_class=info.get("python_class"))
    return info


def pin_java_path(config_path: Path) -> str | None:
    """Replace a bare `java` with the absolute path it resolves to now.

    A startup task may not see the same PATH as your PowerShell window, so a
    bare `java` that works manually can fail at boot. Returns the new value,
    or None if nothing needed changing.
    """
    from agent.config import Config
    config = Config.load(config_path)
    current = config.server.java
    if config.server.raw_command or Path(current).is_absolute():
        return None
    resolved = shutil.which(current)
    if not resolved:
        raise AutostartError(
            f"server.java is '{current}', which is not on PATH for this account either. "
            "Set server.java in config.yaml to the full path of java.exe."
        )
    config.set("server.java", str(Path(resolved).resolve()))
    config.save()
    return str(Path(resolved).resolve())


def enable(mode: str = "boot", pin_java: bool = True, executable: str | None = None) -> dict[str, Any]:
    _require_windows()
    if mode not in MODES:
        raise AutostartError(f"mode must be one of {MODES}")
    if mode == "boot" and is_admin() is False:
        raise AutostartError(
            "Registering a task that runs at boot without anyone logged in requires an "
            "Administrator PowerShell. Right-click PowerShell -> Run as administrator, "
            "or use --logon to start when you log in instead (no administrator needed)."
        )
    problems = interpreter_problems(executable)
    if problems:
        raise AutostartError("\n".join(problems))

    report: dict[str, Any] = {"mode": mode, "actions": []}

    removed = remove_legacy_service()
    if removed is not None:
        cls = removed.get("python_class")
        if cls and removed.get("python_class_valid") is False:
            why = f"it was registered with PythonClass={cls!r}, so it could never start"
        elif cls:
            why = f"PythonClass={cls!r}"
        else:
            why = "its PythonClass value could not be read"
        report["actions"].append(
            f"Removed the old Windows Service '{LEGACY_SERVICE}' ({why}; it would also "
            "conflict with the scheduled task).")

    if pin_java:
        pinned = pin_java_path(PROJECT_ROOT / "config" / "config.yaml")
        if pinned:
            report["actions"].append(f"Set server.java to the absolute path {pinned}")

    launch = expected_launch(executable)
    user = current_user()
    xml = build_task_xml(mode, user, launch["command"], launch["arguments"],
                         launch["working_directory"])
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as fh:
        fh.write(xml)
        xml_path = fh.name
    try:
        # /F replaces an existing task of the same name, so re-running enable
        # never creates a duplicate.
        code, out, err = run_tool(["schtasks.exe", "/Create", "/TN", TASK_NAME,
                                   "/XML", xml_path, "/F"])
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass
    if code != 0:
        message = (err or out).strip()
        hint = ""
        if "access is denied" in message.lower():
            hint = " Run PowerShell as Administrator."
        raise AutostartError(f"schtasks could not create the task: {message}.{hint}")

    registered = query_task()
    if not registered or "parse_error" in registered:
        raise AutostartError("schtasks reported success but the task could not be read back")
    mismatches = compare_to_expected(registered, launch)
    if mismatches:
        raise AutostartError("The task was created but does not match what was requested: "
                             + "; ".join(mismatches))
    startup_diag.append_event("setup.log", "startup_task_created", task=TASK_NAME, mode=mode, user=user, **launch)
    report.update({"registered": registered, "user": user, "launch": launch})
    report["actions"].append(f"Registered scheduled task '{TASK_NAME}' ({mode} mode) and read it back")
    return report


def disable() -> dict[str, Any]:
    _require_windows()
    if query_task() is None:
        return {"removed": False, "detail": f"No task named '{TASK_NAME}' is registered"}
    run_tool(["schtasks.exe", "/End", "/TN", TASK_NAME])
    code, out, err = run_tool(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0:
        raise AutostartError(f"schtasks could not delete the task: {(err or out).strip()}")
    startup_diag.append_event("setup.log", "startup_task_removed", task=TASK_NAME)
    return {"removed": True,
            "detail": f"Removed '{TASK_NAME}'. The agent will no longer start with Windows. "
                      "If it is running now, it has been stopped; Minecraft keeps running only "
                      "if it was started separately."}


def run_now() -> dict[str, Any]:
    _require_windows()
    code, out, err = run_tool(["schtasks.exe", "/Run", "/TN", TASK_NAME])
    if code != 0:
        raise AutostartError(f"schtasks could not start the task: {(err or out).strip()}")
    return {"result": "REQUESTED",
            "detail": "Task Scheduler was asked to start the agent. Check logs/startup.log or "
                      "run the test command in ~20 seconds to see whether it initialised."}


def report(executable: str | None = None) -> dict[str, Any]:
    """The "Test Windows Startup" report. Every field comes from Windows or
    from the agent's own startup log; nothing is inferred."""
    expected = expected_launch(executable)
    out: dict[str, Any] = {
        "supported": IS_WINDOWS,
        "platform": sys.platform,
        "task_name": TASK_NAME,
        "expected": expected,
        "interpreter_problems": interpreter_problems(executable),
        "last_startup": startup_diag.read_last(),
        "recent_events": startup_diag.tail(15),
        "startup_log": str(startup_diag.STARTUP_LOG),
        "problems": [],
    }
    if not IS_WINDOWS:
        out.update(mechanism=None, registered=None, points_to_current_app=None,
                   verdict="unsupported",
                   detail="Windows startup can only be inspected on Windows.")
        return out

    task = query_task()
    service = legacy_service()
    others = other_startup_entries()
    out["legacy_service"] = service
    out["other_entries"] = others

    if task and "parse_error" not in task:
        out["mechanism"] = "Task Scheduler"
        out["registered"] = True
        out["task"] = task
        out["runtime"] = task_runtime()
        mismatches = compare_to_expected(task, expected)
        out["points_to_current_app"] = not mismatches
        out["problems"].extend(mismatches)
    elif task:
        out["mechanism"] = "Task Scheduler"
        out["registered"] = True
        out["points_to_current_app"] = None
        out["problems"].append(f"The task exists but its definition could not be read: {task['parse_error']}")
    else:
        out["mechanism"] = "Windows Service (legacy)" if service["exists"] else None
        out["registered"] = False
        out["points_to_current_app"] = None

    if service["exists"]:
        if service["python_class_valid"] is False:
            out["problems"].append(
                f"The old Windows Service '{LEGACY_SERVICE}' is registered with PythonClass="
                f"{service['python_class']!r}. That can never start. "
                "Run: python -m installer.autostart enable  (it removes the service).")
        else:
            out["problems"].append(
                f"The old Windows Service '{LEGACY_SERVICE}' still exists alongside the task. "
                "Two startup mechanisms will fight over the same port.")
    for entry in others:
        out["problems"].append(f"Another startup entry also launches the agent: "
                               f"{entry['kind']} at {entry['location']}")
    out["problems"].extend(out["interpreter_problems"])

    if not out["registered"]:
        out["verdict"] = "not registered"
    elif out["problems"]:
        out["verdict"] = "problems found"
    else:
        out["verdict"] = "registered correctly"
    return out


# ======================================================================
# CLI
# ======================================================================
def render(data: dict[str, Any]) -> str:
    lines = ["", "Test Windows Startup", "=" * 62]
    lines.append(f"  Verdict                 : {data['verdict'].upper()}")
    if not data["supported"]:
        lines.append(f"  {data.get('detail')}")
        return "\n".join(lines)
    lines.append(f"  Startup registration    : {'FOUND' if data['registered'] else 'NOT FOUND'}")
    lines.append(f"  Startup mechanism       : {data.get('mechanism') or 'none'}")
    task = data.get("task") or {}
    if task:
        lines.append(f"  Mode                    : {task.get('mode')} "
                     f"({'runs at boot, no login needed' if task.get('mode') == 'boot' else 'runs when you log in'})")
        lines.append(f"  Runs as                 : {task.get('user')} "
                     f"[{task.get('logon_type')}, {task.get('run_level')}]")
        lines.append(f"  Registered executable   : {task.get('command')}")
        lines.append(f"  Registered arguments    : {task.get('arguments')}")
        lines.append(f"  Registered working dir  : {task.get('working_directory')}")
        lines.append(f"  Enabled                 : {task.get('enabled')}")
        lines.append("  Keep-alive              : "
                     + ", ".join(f"{t['type']}{' every ' + t['repeat_every'] if t['repeat_every'] else ''}"
                                 for t in task.get("triggers", [])))
    lines.append(f"  Points to this install  : "
                 f"{ {True: 'YES', False: 'NO', None: 'unknown'}[data.get('points_to_current_app')] }")
    lines.append(f"  This install would run  : {data['expected']['command']} "
                 f"{data['expected']['arguments']}")
    lines.append(f"                 in       : {data['expected']['working_directory']}")
    runtime = data.get("runtime") or {}
    if runtime:
        lines.append(f"  Task status             : {runtime.get('status') or 'unknown'}")
        lines.append(f"  Last run (Windows)      : {runtime.get('last_run_time') or 'unknown'}")
        lines.append(f"  Last result (Windows)   : {runtime.get('last_result') or 'unknown'}")
        lines.append(f"  Next run                : {runtime.get('next_run_time') or 'unknown'}")
    service = data.get("legacy_service") or {}
    lines.append(f"  Old Windows Service     : "
                 f"{'present - ' + str(service.get('state')) if service.get('exists') else 'not present'}")
    last = data.get("last_startup")
    lines.append("")
    lines.append("Last startup attempt recorded by the agent")
    lines.append("-" * 62)
    if last:
        lines.append(f"  Started                 : {last.get('started_at')}")
        lines.append(f"  Launched by             : {last.get('launched_by')}")
        lines.append(f"  Executable              : {last.get('executable')}")
        lines.append(f"  Working directory       : {last.get('cwd')}")
        lines.append(f"  Outcome                 : {last.get('outcome')}")
        lines.append(f"  Last stage reached      : {last.get('last_event')} at {last.get('last_event_ts')}")
        initialised = any(e.get("event") == "controller_initialized" for e in last.get("events", []))
        lines.append(f"  Controller initialised  : {'YES' if initialised else 'NO'}")
        for event in last.get("events", [])[-6:]:
            extra = event.get("error") or event.get("detail") or ""
            lines.append(f"    {event['ts']}  {event['event']}{'  - ' + str(extra) if extra else ''}")
    else:
        lines.append("  No startup has been recorded yet.")
    lines.append(f"  Full log                : {data['startup_log']}")
    if data["problems"]:
        lines.append("")
        lines.append("Problems")
        lines.append("-" * 62)
        for problem in data["problems"]:
            lines.append(f"  - {problem}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the agent automatically with Windows")
    sub = parser.add_subparsers(dest="command", required=True)
    enable_p = sub.add_parser("enable", help="Register the startup task")
    enable_p.add_argument("--logon", action="store_true",
                          help="Start when you log in, instead of at boot")
    enable_p.add_argument("--no-pin-java", action="store_true",
                          help="Leave server.java as it is in config.yaml")
    sub.add_parser("disable", help="Remove the startup task")
    sub.add_parser("status", help="Short summary")
    test_p = sub.add_parser("test", help="Full Test Windows Startup report")
    test_p.add_argument("--json", action="store_true")
    sub.add_parser("run", help="Start the task now, the way Windows would")
    args = parser.parse_args(argv)

    try:
        if args.command == "enable":
            result = enable("logon" if args.logon else "boot", pin_java=not args.no_pin_java)
            for action in result["actions"]:
                print(f"  - {action}")
            print(render(report()))
            print("Start it now without rebooting:  python -m installer.autostart run")
            return 0
        if args.command == "disable":
            print(disable()["detail"])
            return 0
        if args.command == "run":
            print(run_now()["detail"])
            return 0
        data = report()
        if args.command == "test" and args.json:
            print(json.dumps(data, indent=2, default=str))
        elif args.command == "status":
            print(f"{data['verdict']}: mechanism={data.get('mechanism')}, "
                  f"points_to_current_app={data.get('points_to_current_app')}")
        else:
            print(render(data))
        return 0 if data["verdict"] in ("registered correctly", "unsupported") else 1
    except AutostartError as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
