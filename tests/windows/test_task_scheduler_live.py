"""Live Task Scheduler test. Runs only on Windows with MCSC_LIVE_WINDOWS_TESTS=1
(the GitHub Actions workflow sets it). It registers a real scheduled task
under the unique name in MCSC_TASK_NAME, so it cannot collide with a real
installation, reads it back from Windows, launches it, and removes it."""

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("MCSC_LIVE_WINDOWS_TESTS") != "1",
    reason="live Windows Task Scheduler test (CI only)")

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def autostart():
    assert os.environ.get("MCSC_TASK_NAME", "").startswith("MCSC CI"), "use an isolated task name"
    from installer import autostart as module
    assert module.TASK_NAME == os.environ["MCSC_TASK_NAME"]
    yield module
    if module.query_task() is not None:      # never leave a task behind
        module.disable()


def test_boot_task_registers_verifies_launches_and_removes(autostart):
    assert autostart.is_admin() is True, "the GitHub Windows runner is expected to be elevated"
    result = autostart.enable("boot", pin_java=False)
    task = result["registered"]
    assert task["command"].lower().endswith("pythonw.exe")
    assert Path(task["working_directory"]).resolve() == PROJECT.resolve()
    assert task["arguments"] == "-m agent.main --launched-by task"
    assert task["logon_type"] == "S4U"
    assert task["run_level"] == "LeastPrivilege"
    assert task["execution_time_limit"] == "PT0S"
    assert task["multiple_instances"] == "IgnoreNew"
    assert task["stops_on_battery"] is False

    report = autostart.report()
    assert report["verdict"] == "registered correctly", report["problems"]
    assert report["points_to_current_app"] is True

    # Launch it the way Windows would and prove the agent really started from
    # the task: the startup log records launched_by=task and the project folder.
    log = PROJECT / "logs" / "startup.log"
    offset = log.stat().st_size if log.exists() else 0
    autostart.run_now()
    record = None
    for _ in range(90):
        time.sleep(1)
        if log.exists():
            with open(log, encoding="utf-8") as fh:
                fh.seek(offset)
                for line in fh:
                    entry = json.loads(line)
                    if entry.get("event") == "process_started" and entry.get("launched_by") == "task":
                        record = entry
                        break
        if record:
            break
    assert record, "the scheduled task did not start the agent within 90 seconds"
    assert Path(record["cwd"]).resolve() == PROJECT.resolve()
    assert record["executable"].lower().endswith("pythonw.exe")

    removal = autostart.disable()
    assert removal["removed"] is True
    assert autostart.query_task() is None
    assert autostart.report()["registered"] is False


def test_registering_twice_does_not_duplicate(autostart):
    autostart.enable("boot", pin_java=False)
    autostart.enable("logon", pin_java=False)
    assert autostart.query_task()["mode"] == "logon"
    code, out, _ = autostart.run_tool(["schtasks.exe", "/Query", "/FO", "CSV", "/NH"])
    assert out.count(autostart.TASK_NAME) == 1
    autostart.disable()
    assert autostart.query_task() is None
