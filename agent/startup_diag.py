"""Startup diagnostics.

When Windows launches the agent there is no console to read, so everything
that happens between "process created" and "controller initialized" is
written here.

The log lives at <project>/logs/startup.log. That location is derived from
this file's own path, so it is available *before* configuration is loaded -
which matters, because a broken config.yaml is one of the things this log
needs to be able to record.

Format: one JSON object per line, each with a timestamp, so the file can be
read by a person or parsed by the "Test Windows Startup" report.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# MCSC_STARTUP_LOG_DIR exists so the test suite can write somewhere disposable
# instead of overwriting the real record of the last Windows startup.
STARTUP_LOG_DIR = Path(os.environ.get("MCSC_STARTUP_LOG_DIR") or (PROJECT_ROOT / "logs"))
STARTUP_LOG = STARTUP_LOG_DIR / "startup.log"
LAST_STARTUP = STARTUP_LOG_DIR / "last_startup.json"
CONSOLE_LOG = STARTUP_LOG_DIR / "console.log"


def set_log_dir(path: Path) -> None:
    """Point the diagnostics at another directory (used by tests)."""
    global STARTUP_LOG_DIR, STARTUP_LOG, LAST_STARTUP, CONSOLE_LOG
    STARTUP_LOG_DIR = Path(path)
    STARTUP_LOG = STARTUP_LOG_DIR / "startup.log"
    LAST_STARTUP = STARTUP_LOG_DIR / "last_startup.json"
    CONSOLE_LOG = STARTUP_LOG_DIR / "console.log"
    _session.clear()
MAX_LOG_BYTES = 2_000_000

_lock = threading.Lock()
_session: dict[str, Any] = {}


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _rotate() -> None:
    try:
        if STARTUP_LOG.is_file() and STARTUP_LOG.stat().st_size > MAX_LOG_BYTES:
            backup = STARTUP_LOG.with_suffix(".log.1")
            backup.unlink(missing_ok=True)
            STARTUP_LOG.rename(backup)
    except OSError:
        pass


def record(event: str, **fields: Any) -> None:
    """Append one timestamped event. Never raises: diagnostics must not be
    the thing that stops the agent starting."""
    entry = {"ts": _now(), "pid": os.getpid(), "event": event, **fields}
    try:
        with _lock:
            STARTUP_LOG_DIR.mkdir(parents=True, exist_ok=True)
            _rotate()
            with open(STARTUP_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
            if not _session.get("started_at"):
                return  # not an agent startup (e.g. a CLI tool): keep last_startup.json as it was
            if _session.get("outcome") not in (None, "in progress"):
                return  # this process's startup record is closed; keep it as written
            _session.setdefault("events", []).append(
                {"ts": entry["ts"], "event": event,
                 **{k: v for k, v in fields.items() if k in ("detail", "error", "ok")}}
            )
            _session["last_event"] = event
            _session["last_event_ts"] = entry["ts"]
            _write_last()
    except Exception:
        pass


def _write_last() -> None:
    try:
        LAST_STARTUP.write_text(json.dumps(_session, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def append_event(log_name: str, event: str, **fields: Any) -> None:
    """Write one structured event to logs/<log_name> without touching the
    startup record. Used by setup and other command-line tools. Never raises."""
    entry = {"ts": _now(), "pid": os.getpid(), "event": event, **fields}
    try:
        with _lock:
            STARTUP_LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(STARTUP_LOG_DIR / log_name, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def begin(argv: list[str], launched_by: str) -> None:
    """First thing main() does. Captures the facts needed to debug a launch
    that happened with nobody watching."""
    _session.clear()
    _session.update({
        "started_at": _now(),
        "pid": os.getpid(),
        "launched_by": launched_by,
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "argv": list(argv),
        "project_root": str(PROJECT_ROOT),
        "user": os.environ.get("USERNAME") or os.environ.get("USER"),
        "session_name": os.environ.get("SESSIONNAME"),
        "stdout_attached": sys.stdout is not None,
        "outcome": "in progress",
        "events": [],
    })
    record("process_started",
           launched_by=launched_by,
           executable=sys.executable,
           cwd=os.getcwd(),
           argv=list(argv),
           python=sys.version.split()[0],
           user=_session["user"],
           session_name=_session["session_name"],
           path_env=os.environ.get("PATH", "")[:2000])


def finish(outcome: str, **fields: Any) -> None:
    # Record the final event while the session is still open, then close it.
    # (Closing first would make record() discard the very event that says how
    # the process ended.)
    record("process_finished", outcome=outcome, **fields)
    with _lock:
        _session["outcome"] = outcome
        _session["finished_at"] = _now()
        _session.update({k: v for k, v in fields.items() if isinstance(v, (str, int, float, bool))})
        _write_last()


def record_exception(where: str, exc: BaseException) -> None:
    record("exception", where=where, error=f"{type(exc).__name__}: {exc}",
           traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-6000:])


def attach_streams_if_missing() -> bool:
    """pythonw.exe and scheduled tasks start with no stdout/stderr. Anything
    that writes to them would either vanish or, for some libraries, raise.
    Redirect them to a file so output is kept and nothing trips over None.

    Returns True when a redirect was needed."""
    if sys.stdout is not None and sys.stderr is not None:
        return False
    try:
        STARTUP_LOG_DIR.mkdir(parents=True, exist_ok=True)
        stream = open(CONSOLE_LOG, "a", encoding="utf-8", buffering=1)
        stream.write(f"\n===== {_now()} console output (pid {os.getpid()}) =====\n")
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
        return True
    except OSError:
        return False


def install_excepthook() -> None:
    previous = sys.excepthook

    def hook(exc_type, exc, tb):
        try:
            record("unhandled_exception", error=f"{exc_type.__name__}: {exc}",
                   traceback="".join(traceback.format_exception(exc_type, exc, tb))[-6000:])
        finally:
            previous(exc_type, exc, tb)

    sys.excepthook = hook

    def thread_hook(args):
        record("unhandled_thread_exception", thread=getattr(args.thread, "name", "?"),
               error=f"{args.exc_type.__name__}: {args.exc_value}")

    threading.excepthook = thread_hook


def read_last() -> dict[str, Any] | None:
    try:
        return json.loads(LAST_STARTUP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def tail(lines: int = 40) -> list[dict[str, Any]]:
    try:
        raw = STARTUP_LOG.read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
