"""Application logging with rotation.

Agent logs live in <data_dir>/logs/agent.log (rotated) so they never mix with
the Minecraft server's own logs.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path, level: str = "INFO", console: bool = True) -> logging.Logger:
    global _CONFIGURED
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if _CONFIGURED:
        return logging.getLogger("msc")

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "agent.log", maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "agent-errors.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(fmt)
    root.addHandler(err_handler)

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(fmt)
        root.addHandler(stream)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True
    return logging.getLogger("msc")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"msc.{name}")
