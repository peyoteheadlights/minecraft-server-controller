"""Get help: one zip someone can send to whoever is helping them.

It holds what is needed to see what went wrong, and nothing that would let
the reader into the PC or the worlds:

  * this app's own logs (agent.log, agent-errors.log, their rotated copies)
  * the startup and install logs (startup.log, setup.log, console.log)
  * the ``--check`` report, run fresh
  * version information: this app, Python, Windows, and each server's type

Never included: .env, config.yaml (it holds paths and email settings, and
the report already covers what matters), the database, certificates, world
files, backups, or the Minecraft servers' own logs (they hold players' IP
addresses and chat). Every text file is passed through ``redact`` first, so a
secret that ended up in a log line by mistake is cut out too.

The file list is shown before the zip is made (``plan``), and the zip holds
exactly that list.
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import secrets
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, startup_diag
from .config import SECRET_ENV_KEYS

FOLDER = "help-bundles"
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_FILE_BYTES = 5 * 1024 * 1024  # the newest part of a bigger log
KEEP_SECONDS = 24 * 3600
LOG_NAMES = re.compile(r"^(agent|agent-errors)\.log(\.\d+)?$")
INSTALL_LOGS = ("startup.log", "startup.log.1", "setup.log", "console.log", "last_startup.json")

PATTERNS = [
    (re.compile(r"pbkdf2_sha256\$[^\s\"',]+"), "[password hash removed]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [removed]"),
    (re.compile(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\S+"), "[webhook removed]"),
    (
        re.compile(r"(?i)\b(token|password|secret|passphrase|api_key)(\s*[=:]\s*)\S+"),
        r"\1\2[removed]",
    ),
]


@dataclass
class Item:
    name: str  # the name inside the zip
    source: Path | None  # a file to read, or None for generated text
    size: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "note": self.note}


def secret_values() -> list[str]:
    """The actual secret values in use, so a log line holding one is cut."""
    values = []
    for key in SECRET_ENV_KEYS:
        value = os.environ.get(key, "")
        if len(value) >= 6:
            values.append(value)
    return sorted(values, key=len, reverse=True)


def redact(text: str, values: list[str] | None = None) -> str:
    for value in values if values is not None else secret_values():
        text = text.replace(value, "[removed]")
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _logs(config) -> list[Item]:
    items: list[Item] = []
    log_dir = Path(config.log_dir)
    if log_dir.is_dir():
        for path in sorted(log_dir.iterdir()):
            if LOG_NAMES.match(path.name) and path.is_file() and not path.is_symlink():
                items.append(Item(f"logs/{path.name}", path, path.stat().st_size, "app log"))
    install_dir = startup_diag.STARTUP_LOG_DIR
    for name in INSTALL_LOGS:
        path = install_dir / name
        if path.is_file() and not path.is_symlink():
            items.append(
                Item(f"install/{name}", path, path.stat().st_size, "install and startup log")
            )
    return items


def plan(config) -> list[Item]:
    """What the zip will hold, shown before it is made."""
    return [
        *_logs(config),
        Item("check-report.txt", None, 0, "the system check (--check), run now"),
        Item("version.json", None, 0, "app, Python and Windows versions, server types"),
    ]


def version_info(config) -> dict[str, Any]:
    servers = []
    for server_id in config.server_ids:
        view = config.for_server(server_id)
        servers.append({"id": server_id, "type": view.server.type})
    return {
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "made_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "servers": servers,
    }


def _tail(path: Path) -> bytes:
    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        if size > MAX_FILE_BYTES:
            fh.seek(size - MAX_FILE_BYTES)
        return fh.read()


def build(config, target: Path, report_text: str | None = None) -> list[dict[str, Any]]:
    """Write the zip. Returns the list of what went in (the same as plan)."""
    from .diagnostics import run_diagnostics

    values = secret_values()
    items = plan(config)
    written = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if item.name == "check-report.txt":
                text = report_text if report_text is not None else run_diagnostics(config).render()
            elif item.name == "version.json":
                text = json.dumps(version_info(config), indent=2)
            else:
                assert item.source is not None
                try:
                    text = _tail(item.source).decode("utf-8", errors="replace")
                except OSError as exc:
                    text = f"(couldn't be read: {exc})"
            data = redact(text, values).encode("utf-8")
            zf.writestr(item.name, data)
            written.append({"name": item.name, "size": len(data), "note": item.note})
        listing = io.StringIO()
        listing.write("What this zip holds. Passwords, keys and world files are never in it.\n\n")
        for entry in written:
            listing.write(f"{entry['name']}  ({entry['size']} bytes)  {entry['note']}\n")
        zf.writestr("README.txt", listing.getvalue())
    return written


def folder(config) -> Path:
    path = Path(config.data_dir) / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in path.iterdir():
        try:
            if now - old.stat().st_mtime > KEEP_SECONDS:
                old.unlink()
        except OSError:
            pass
    return path


def new_target(config) -> tuple[str, Path]:
    token = secrets.token_hex(16)
    return token, folder(config) / f"{token}.zip"


def path_for(config, token: str) -> Path | None:
    if not TOKEN_RE.match(token or ""):
        return None
    path = folder(config) / f"{token}.zip"
    return path if path.is_file() else None
