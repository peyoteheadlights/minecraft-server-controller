"""Sessions, TLS certificate facts and the audit log."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from ...security.auth import Principal
from ..deps import audit, get_core, require_auth

router = APIRouter()


@router.get("/security")
async def security_overview(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {
        "agent_connected": True,
        "tls": core.metrics.certificate_status(),
        "https_enabled": core.config.tls_enabled,
        "dashboard_hostname": core.config.dashboard_hostname or None,
        "tailscale": await asyncio.to_thread(core.metrics.tailscale_status),
        "authentication": {
            "enabled": core.auth.configured,
            "session_hours": core.config.security.session_hours,
            "api_token_configured": bool(core.config.api_token),
        },
        "active_sessions": core.auth.active_sessions(),
        "failed_logins_24h": core.auth.failed_login_count(24),
        "bind_address": f"{core.config.network.host}:{core.config.network.port}",
    }


@router.get("/security/audit")
async def audit_log(
    limit: int = 100, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    limit = max(1, min(int(limit), 500))
    return {"entries": core.db.audit_entries(limit)}


@router.post("/security/revoke-sessions")
async def revoke_sessions(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    count = core.auth.revoke_all()
    audit(core, request, "revoke_all_sessions", detail=str(count))
    return {"ok": True, "revoked": count}


@router.get("/security/tls")
async def tls_status(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """Certificate facts read from disk.

    Only metadata is returned. The private key is never read into a response,
    never logged, and has no endpoint of its own - the only thing reported
    about it is whether its public half matches the certificate.
    """
    return {
        "enabled": core.config.tls_enabled,
        "certificate": core.metrics.certificate_status(),
        "hostname": core.config.dashboard_hostname or None,
        "hsts": core.config.tls.hsts,
        "http_redirect": core.config.tls.http_redirect,
        "renewal": "Run 'python -m installer.make_certs --renew' on the server PC. "
        "Tailscale-issued certificates renew automatically.",
    }
