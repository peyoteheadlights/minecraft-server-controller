"""Live Task Scheduler test. Runs only on Windows with MCSC_LIVE_WINDOWS_TESTS=1
(the GitHub Actions workflow sets it). It registers a real scheduled task
under the unique name in MCSC_TASK_NAME, so it cannot collide with a real
installation, reads it back from Windows, launches it, and removes it."""

import csv
import io
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


def read_new_log_entries(log: Path, offset: int) -> list[dict]:
    if not log.exists():
        return []
    entries = []
    with open(log, encoding="utf-8") as fh:
        fh.seek(offset)
        for line in fh:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # a line still being written; it is read again next time
    return entries


def test_boot_task_registers_verifies_launches_and_removes(autostart):
    assert autostart.is_admin() is True, "the GitHub Windows runner is expected to be elevated"
    # Remember where the log ends before registering, so a start triggered by
    # the registration itself is not missed.
    log = PROJECT / "logs" / "startup.log"
    offset = log.stat().st_size if log.exists() else 0
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
    autostart.run_now()
    record = None
    for _ in range(90):
        time.sleep(1)
        record = next((e for e in read_new_log_entries(log, offset)
                       if e.get("event") == "process_started" and e.get("launched_by") == "task"), None)
        if record:
            break
    if not record:
        runtime = autostart.task_runtime()
        tail = read_new_log_entries(log, offset)[-10:]
        pytest.fail("The scheduled task did not start the agent within 90 seconds. "
                    f"Windows reports status={runtime['status']!r}, "
                    f"last result={runtime['last_result']!r}. New startup.log entries: {tail}")
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
    # schtasks prints one CSV row per trigger, so count distinct task names.
    code, out, _ = autostart.run_tool(["schtasks.exe", "/Query", "/FO", "CSV", "/NH"])
    assert code == 0
    names = {row[0] for row in csv.reader(io.StringIO(out)) if row}
    ours = {name for name in names if autostart.TASK_NAME in name}
    assert ours == {"\\" + autostart.TASK_NAME}, f"expected one task, found {sorted(ours)}"
    # Replaced, not merged: exactly the logon trigger and the keep-alive trigger.
    triggers = [t["type"] for t in autostart.query_task()["triggers"]]
    assert sorted(triggers) == ["LogonTrigger", "TimeTrigger"], triggers
    autostart.disable()
    assert autostart.query_task() is None
