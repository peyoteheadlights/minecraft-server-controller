"""The pairing code: how a phone finds this PC.

One small format, shown as a QR code on the installer's last screen and on
the "Open on your phone" card in App settings. It is an ordinary link, so a
phone's camera opens the dashboard in the browser today, and the phone app
(Phase 9) reads the same link to pair:

    https://<address>:<port>/?pair=1&fp=<certificate SHA-256>&api=<API version>

* ``address``: the name the dashboard's certificate is for (the PC's
  Tailscale name), else the PC's Tailscale address. Never guessed: when
  neither is known, there is no code and the reason says why.
* ``fp``: the SHA-256 fingerprint of the agent's certificate, 64 hex
  digits, so an app can pin it instead of switching certificate checks off.
  A new certificate means a new code, and phones scan again.
* ``api``: ``agent.API_VERSION``.

It never holds the password, a token or any other secret.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from . import API_VERSION
from .security.tls import fingerprint


def certificate_fingerprint(config) -> str | None:
    """The agent certificate's SHA-256, as 64 lowercase hex digits."""
    cert = config.tls_certificate if config.tls_enabled else None
    if cert is None or not cert.is_file():
        return None
    value = fingerprint(cert)
    return value.replace(":", "").lower() if value else None


def _address(config) -> tuple[str | None, str]:
    hostname = config.dashboard_hostname
    if hostname:
        return hostname, "the certificate's name"
    try:
        from .tailscale import tailscale_status

        status = tailscale_status()
        if status.get("dns_name"):
            return str(status["dns_name"]).rstrip("."), "this PC's Tailscale name"
        ipv4 = [a for a in status.get("addresses") or [] if ":" not in str(a)]
        if ipv4:
            return str(ipv4[0]), "this PC's Tailscale address"
    except Exception:
        pass
    return None, ""


def pairing_code(config) -> dict[str, Any]:
    """The code, its parts and its QR squares, or why there isn't one."""
    port = config.network.port
    fp = certificate_fingerprint(config)
    address, source = _address(config)
    base: dict[str, Any] = {
        "ok": False,
        "address": address,
        "address_source": source or None,
        "port": port,
        "fingerprint": fp,
        "api_version": API_VERSION,
        "url": None,
        "address_url": None,
        "qr": None,
        "reason": None,
    }
    if not config.tls_enabled:
        base["reason"] = "HTTPS is turned off, so a phone can't connect safely."
        return base
    if fp is None:
        base["reason"] = "The agent's certificate couldn't be read."
        return base
    if address is None:
        base["reason"] = (
            "This PC's Tailscale name isn't known yet. Sign in to Tailscale on the PC, "
            "then open this again."
        )
        return base
    address_url = f"https://{address}:{port}/"
    url = address_url + "?" + urlencode({"pair": 1, "fp": fp, "api": API_VERSION})
    base.update(ok=True, url=url, address_url=address_url, qr=qr_rows(url))
    return base


def qr_rows(text: str) -> list[str]:
    """The QR code as rows of 0 and 1 (1 is a dark square), with no quiet
    border. The dashboard draws it square by square, black on white, so
    phone cameras read it in dark mode too, and no picture markup from the
    server is ever put into the page."""
    import segno

    code = segno.make(text, error="m")
    return ["".join("1" if cell else "0" for cell in row) for row in code.matrix]
