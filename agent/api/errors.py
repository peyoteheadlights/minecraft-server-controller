"""How domain errors become HTTP responses.

Managers raise their own errors (ServerError, BackupError, ...). Routes let
them propagate; the handlers registered here turn each into a JSON error with
the right status code, so route code does not repeat try/except blocks.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..backups.manager import BackupError
from ..config import ConfigError
from ..core import UnknownServer
from ..crossplay import CrossplayError
from ..downloads import DownloadError
from ..duplicate import DuplicateError
from ..jobs import JobConflict, JobNotFound
from ..memory import MemoryLimitError
from ..minecraft.chat import ChatError
from ..minecraft.commands import CommandError
from ..minecraft.playeractions import PlayerActionError
from ..minecraft.process import ServerError
from ..minecraft.properties import FormError, PropertiesError
from ..modpack import ModpackError
from ..mods.dependencies import DependencyError
from ..mods.manager import ModError
from ..mods.modrinth import ModrinthError
from ..notifications.push import PushError
from ..safechange import SafeChangeError
from ..scheduler.scheduler import ScheduleError
from ..security.auth import AuthError
from ..security.paths import PathSafetyError
from ..servertypes import UnknownServerType
from ..servertypes.install import InstallError
from ..servertypes.versions import VersionError
from ..transfer import TransferError
from ..worldimport import WorldImportError
from ..worldundo import WorldUndoError
from .deps import audit

# The default status for each domain error.
ERROR_STATUS: dict[type[Exception], int] = {
    ServerError: 409,  # the server is in the wrong state for this
    CommandError: 400,
    BackupError: 400,
    ModError: 400,
    DependencyError: 400,
    ScheduleError: 400,
    PathSafetyError: 400,
    ModrinthError: 502,  # Modrinth failed, not the request
    UnknownServer: 404,
    JobNotFound: 404,
    JobConflict: 409,  # another change is already running on that server
    SafeChangeError: 400,
    ConfigError: 400,
    UnknownServerType: 400,
    VersionError: 502,  # the official source could not be read, or has no such version
    DownloadError: 502,  # the download failed, not the request
    InstallError: 400,
    CrossplayError: 400,
    PlayerActionError: 400,
    PropertiesError: 400,
    DuplicateError: 400,
    ModpackError: 400,
    ChatError: 400,
    WorldUndoError: 409,  # the server has to be off first
    PushError: 400,
    WorldImportError: 400,
    MemoryLimitError: 400,
    TransferError: 400,
}
DOMAIN_ERRORS: tuple[type[Exception], ...] = tuple(ERROR_STATUS)


def _status_handler(status: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


async def _auth_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthError)
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(status_code=exc.status, content={"detail": exc.message}, headers=headers)


async def _form_handler(request: Request, exc: Exception) -> JSONResponse:
    """A form with several refused values: each one's reason, by key."""
    assert isinstance(exc, FormError)
    return JSONResponse(status_code=400, content={"detail": str(exc), "problems": exc.problems})


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, status in ERROR_STATUS.items():
        app.add_exception_handler(exc_type, _status_handler(status))
    app.add_exception_handler(FormError, _form_handler)
    app.add_exception_handler(AuthError, _auth_handler)


@contextmanager
def respond_as(status: int) -> Iterator[None]:
    """Report any domain error raised inside the block with this status,
    for routes where the default does not fit (a lookup that means 404)."""
    try:
        yield
    except JobConflict:
        raise  # always 409: the request was fine, the timing was not
    except DOMAIN_ERRORS as exc:
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@contextmanager
def audit_failure(
    owner, request: Request, action: str, target: str | None = None, result: str = "failed"
) -> Iterator[None]:
    """Record a domain error raised inside the block in the audit log, then
    let it propagate to its handler."""
    try:
        yield
    except DOMAIN_ERRORS as exc:
        audit(owner, request, action, target=target, result=result, detail=str(exc))
        raise
