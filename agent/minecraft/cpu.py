"""Which CPU cores a Minecraft server may use (its processor affinity).

``server.cpu_cores`` lists the logical cores, counted from 0 as Windows Task
Manager's "Set affinity" does. Empty means every core. When it is set:

  * the agent sets the Java process's affinity right after starting it,
    with the operating system's own call (psutil), never a command line
  * Java is told how many cores it has (``-XX:ActiveProcessorCount``), so
    it sizes its thread pools for those cores, not for the whole PC
  * a change made while the server runs is applied to it at once
  * what the dashboard shows is read back from the running process, never
    taken from the setting

Nothing here can name a program to run: the only input is a list of core
numbers, checked against the cores this PC really has.
"""

from __future__ import annotations

from typing import Any

import psutil

JVM_FLAG = "-XX:ActiveProcessorCount="


def logical_cores() -> int | None:
    """How many logical cores this PC has, or None if it cannot be read."""
    try:
        return psutil.cpu_count(logical=True)
    except Exception:  # pragma: no cover - reported as unknown
        return None


def supported() -> tuple[bool, str]:
    """Whether this operating system lets the agent choose a process's cores."""
    if hasattr(psutil.Process, "cpu_affinity"):
        return True, ""
    return False, "This operating system does not let a program choose which cores another uses"


def shape_problems(value: Any, name: str = "server.cpu_cores") -> list[str]:
    """Problems with the setting itself, whatever PC it is on."""
    if not isinstance(value, list):
        return [f"{name} must be a list of core numbers, for example [0, 1, 2, 3]"]
    problems = []
    for core in value:
        if isinstance(core, bool) or not isinstance(core, int) or core < 0:
            problems.append(f"{name} has {core!r}, which is not a core number (0, 1, 2 ...)")
    if len(set(value)) != len(value):
        problems.append(f"{name} lists a core more than once")
    return problems


def problems(cores: list[int]) -> list[str]:
    """Reasons ``cores`` cannot be used on this PC. Empty: they can."""
    if not cores:
        return []
    found = shape_problems(cores)
    if found:
        return found
    count = logical_cores()
    if count is None:
        return ["This PC's number of cores could not be read, so the core limit cannot be checked"]
    missing = sorted(c for c in cores if c >= count)
    if missing:
        listed = ", ".join(str(c + 1) for c in missing)
        return [
            f"This PC has {count} cores (1 to {count}), so core(s) {listed} do not exist. "
            "Pick the cores again in Settings."
        ]
    return []


def describe(cores: list[int] | None) -> str:
    """Cores as people count them (from 1), with runs shortened: "1-4, 7"."""
    if not cores:
        return "none"
    numbers = sorted(c + 1 for c in cores)
    runs: list[str] = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    runs.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(runs)


def jvm_args(cores: list[int], existing: list[str]) -> list[str]:
    """The flag that tells Java how many cores it has, unless the owner's own
    JVM arguments already say."""
    if not cores or any(str(arg).startswith(JVM_FLAG) for arg in existing):
        return []
    return [f"{JVM_FLAG}{len(cores)}"]


def read(pid: int | None) -> tuple[list[int] | None, str]:
    """The cores the process may use, read from the operating system, or
    (None, why not)."""
    if not pid:
        return None, "The server is not running"
    ok, reason = supported()
    if not ok:
        return None, reason
    try:
        return sorted(psutil.Process(pid).cpu_affinity()), ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
        return None, f"The process's cores could not be read: {exc}"


def apply(pid: int, cores: list[int]) -> dict[str, Any]:
    """Limit the process to ``cores`` (every core when empty), then read the
    result back. ``ok`` is True only when what was read back matches."""
    ok, reason = supported()
    if not ok:
        return {"ok": False, "applied": None, "reason": reason}
    found = problems(cores)
    if found:
        return {"ok": False, "applied": None, "reason": found[0]}
    wanted = sorted(cores) if cores else list(range(logical_cores() or 0))
    try:
        psutil.Process(pid).cpu_affinity(wanted)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError) as exc:
        applied, _ = read(pid)
        return {"ok": False, "applied": applied, "reason": f"The cores could not be set: {exc}"}
    applied, why = read(pid)
    if applied is None:
        return {"ok": False, "applied": None, "reason": why}
    if applied != wanted:
        return {
            "ok": False,
            "applied": applied,
            "reason": "The operating system reports different cores than were asked for",
        }
    return {"ok": True, "applied": applied, "reason": ""}


def status(pid: int | None, cores: list[int]) -> dict[str, Any]:
    """For the dashboard: the setting, and what the process really uses."""
    ok, reason = supported()
    applied, why = read(pid) if ok else (None, reason)
    return {
        "configured": sorted(cores) if cores else None,  # None: every core
        "applied": applied,  # read from the running process; None when unknown
        "applied_reason": why,
        "logical_cores": logical_cores(),
        "supported": ok,
        "unsupported_reason": reason,
        "problems": problems(cores),
    }
