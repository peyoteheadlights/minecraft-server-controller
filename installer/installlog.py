"""The installation log.

Every run writes ``install-<when>.log`` to the app's logs folder, one JSON
object per line in the same shape as ``logs/setup.log`` and
``logs/startup.log`` (``agent/startup_diag.py``): a timestamp, the process
id, the event, and its fields. Each step is logged with its start and end,
its result, what was detected, and on failure the real error, exit code and
the command or file involved.

Secrets never reach the file: field names that hold one (password, hash,
token, key, secret, passphrase) are written as "[hidden]", and every secret
value the run handles is registered with ``hide()`` and replaced wherever
it appears, even inside an error message. The last few logs are kept.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from . import layout

SECRET_FIELD = re.compile(r"pass(word|phrase)?|hash|token|secret|private|vapid|smtp", re.I)
HIDDEN = "[hidden]"


class InstallLog:
    def __init__(self, folder: Path, keep: int = layout.KEEP_INSTALL_LOGS):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.folder / f"install-{stamp}.log"
        n = 1
        while path.exists():
            path = self.folder / f"install-{stamp}-{n}.log"
            n += 1
        self.path = path
        self._secrets: set[str] = set()
        self._lock = threading.Lock()
        self.path.touch()
        self._prune(keep)

    def hide(self, *values: str | None) -> None:
        """Never write these values, wherever they turn up."""
        for value in values:
            if value and len(value) >= 4:
                self._secrets.add(value)

    def scrub(self, value: Any, key: str = "") -> Any:
        if key and SECRET_FIELD.search(key):
            return HIDDEN if value not in (None, "", False) else value
        if isinstance(value, dict):
            return {k: self.scrub(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, str):
            for secret in sorted(self._secrets, key=len, reverse=True):
                value = value.replace(secret, HIDDEN)
        return value

    def write(self, event: str, **fields: Any) -> None:
        entry = {
            "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "event": event,
            **{k: self.scrub(v, k) for k, v in fields.items()},
        }
        line = json.dumps(entry, default=str)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _prune(self, keep: int) -> None:
        logs = sorted(self.folder.glob("install-*.log"), key=lambda p: p.stat().st_mtime)
        for old in logs[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
