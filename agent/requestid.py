"""An ID for each API request, so a log line can be matched to an error a
person saw.

The ID is returned in the ``X-Request-ID`` header of every answer and in the
``request_id`` field of every error answer, and log lines written while the
request is handled end with ``[request <id>]``. Logs stay plain text. A
client may send its own ``X-Request-ID`` (the phone app, for example); one
that isn't 8 to 64 letters, digits or dashes is replaced with a new one.
"""

from __future__ import annotations

import logging
import re
import secrets
from contextvars import ContextVar

HEADER = "X-Request-ID"
_VALID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
current: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_id() -> str:
    return secrets.token_hex(6)


def accept(sent: str | None) -> str:
    """The client's own ID when it is safe to log, otherwise a new one."""
    return sent if sent and _VALID.match(sent) else new_id()


class RequestIdFilter(logging.Filter):
    """Adds ``request_tag`` to every record: `` [request <id>]`` while a
    request is being handled, empty otherwise."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = current.get()
        record.request_tag = f" [request {rid}]" if rid else ""
        return True
