"""Request-scoped dependencies: identity, rate limiting, audit helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..security.auth import AuthError, Principal


def get_core(request: Request):
    core = getattr(request.app.state, "core", None)
    if core is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="The agent is still starting")
    return core


def client_ip(request: Request) -> str:
    core = getattr(request.app.state, "core", None)
    if core and core.config.network.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def require_auth(request: Request, core=Depends(get_core)) -> Principal:
    ip = client_ip(request)
    try:
        core.auth.api_rate.check(f"api:{ip}")
        principal = core.auth.authenticate(bearer_token(request), source_ip=ip)
    except AuthError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status, detail=exc.message, headers=headers) from exc
    request.state.principal = principal
    request.state.client_ip = ip
    return principal


def audit(core, request: Request, action: str, target: str | None = None,
          result: str = "ok", detail: str | None = None) -> None:
    principal = getattr(request.state, "principal", None)
    core.db.audit(
        action,
        user=principal.user if principal else None,
        target=target,
        result=result,
        detail=detail,
        source_ip=getattr(request.state, "client_ip", None),
    )
