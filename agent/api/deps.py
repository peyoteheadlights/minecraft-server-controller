"""Request-scoped dependencies: identity, rate limiting, audit helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response

from ..security.auth import Principal
from ..security.permissions import check_server


def get_core(request: Request):
    core = getattr(request.app.state, "core", None)
    if core is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="The agent is still starting")
    return core


def get_server(request: Request, core=Depends(get_core)):
    """The ServerContext a per-server route acts on.

    Under /api/servers/{server_id}/... it is that server, or a 404. The
    unprefixed routes kept from before there were several servers act on
    the first server in config.yaml.
    """
    server_id = request.path_params.get("server_id")
    if server_id is None:
        return core.default
    ctx = core.servers.get(server_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"There is no server with the id '{server_id}'")
    return ctx


def mark_alias(request: Request, response: Response) -> None:
    """Added to the unprefixed per-server routes, which are kept for one
    release as aliases for the first server."""
    core = getattr(request.app.state, "core", None)
    response.headers["Deprecation"] = "true"
    if core is not None:
        response.headers["Link"] = (
            f'</api/servers/{core.config.default_server_id}>; rel="successor-version"'
        )


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
    # An AuthError raised here is turned into a 401/429 by its handler.
    ip = client_ip(request)
    core.auth.api_rate.check(f"api:{ip}")
    principal = core.auth.authenticate(bearer_token(request), source_ip=ip)
    # The same limit again per account, so one helper on many devices (or
    # many addresses) can't use more than an account's share.
    core.auth.api_rate.check(f"user:{principal.user}")
    request.state.principal = principal
    request.state.client_ip = ip
    return principal


async def server_access(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
) -> None:
    """Added to every per-server route: a helper limited to some servers gets
    a 403 for the others. The unprefixed aliases act on the first server, so
    that is the server checked for them."""
    server_id = request.path_params.get("server_id") or core.config.default_server_id
    check_server(principal, server_id)


def audit(
    owner,
    request: Request,
    action: str,
    target: str | None = None,
    result: str = "ok",
    detail: str | None = None,
) -> None:
    """Record an action in the audit log. ``owner`` is the AgentCore for
    agent-wide actions, or a ServerContext, whose entries name the server."""
    principal = getattr(request.state, "principal", None)
    # The request has its own entry now; the catch-all in main.py adds none.
    request.state.audited = True
    owner.db.audit(
        action,
        user=principal.user if principal else None,
        target=target,
        result=result,
        detail=detail,
        source_ip=getattr(request.state, "client_ip", None),
    )
