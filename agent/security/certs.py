"""Certificate provisioning.

Two strategies, in order of preference:

1. **Tailscale-issued certificates** (`tailscale cert`). Tailscale runs a real
   ACME client against Let's Encrypt using DNS-01 for your tailnet domain, so
   the certificate is signed by a **publicly trusted CA**. Nothing is exposed
   to the internet, no router port is opened, and every browser and phone
   already trusts it with no manual step. Renewal is automatic. This is the
   right answer when it is available, and it is what this module tries first.

2. **A local certificate authority**, generated here. Used when the tailnet has
   no HTTPS certificates available (MagicDNS or HTTPS certs turned off in the
   admin console, or a Tailscale version without `tailscale cert`). A CA
   certificate is created once, you trust it on each device once, and server
   certificates signed by it are trusted from then on. Server certificates are
   issued for 398 days, and re-running this tool renews them without changing
   the CA - so devices never need re-trusting.

Self-signed leaf certificates with no CA are deliberately not offered: they
force a permanent browser warning bypass on every device, which is exactly
what the brief rules out.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .. import tailscale
from ..winproc import NO_WINDOW

log = logging.getLogger("msc.certs")

CA_VALID_DAYS = 3650  # the CA you trust once
LEAF_VALID_DAYS = 398  # the maximum browsers accept for a server certificate


class CertificateError(RuntimeError):
    pass


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def secure_directory(path: Path) -> Path:
    """Create a directory that only the current user can read.

    On Windows the inherited ACL is replaced so that only SYSTEM, the
    Administrators group and the current user have access - the private key
    lives here. A failure is logged; ``folder_access`` says what the folder's
    access really is.
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        try:
            done = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    "SYSTEM:(OI)(CI)F",
                    "/grant:r",
                    "Administrators:(OI)(CI)F",
                    *(["/grant:r", f"{user}:(OI)(CI)F"] if user else []),
                ],
                check=False,
                capture_output=True,
                timeout=30,
                creationflags=NO_WINDOW,
            )
            if done.returncode != 0:
                log.warning(
                    "could not make %s private (icacls exit %s): %s",
                    path,
                    done.returncode,
                    (done.stderr or done.stdout or b"").decode(errors="replace").strip(),
                )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("could not make %s private: %s", path, exc)
    else:
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


# Groups that mean "other people who use this PC". Written as the SDDL
# aliases and SIDs icacls saves, which are the same in every Windows
# language (the names it prints are translated).
SHARED_GROUPS = {
    "WD": "Everyone",
    "S-1-1-0": "Everyone",
    "BU": "Users",
    "S-1-5-32-545": "Users",
    "AU": "Authenticated Users",
    "S-1-5-11": "Authenticated Users",
    "IU": "Interactive users",
    "S-1-5-4": "Interactive users",
    "BG": "Guests",
    "S-1-5-32-546": "Guests",
}


def shared_groups_in_sddl(sddl: str) -> list[str]:
    """The SHARED_GROUPS an SDDL string grants (allows) any access to."""
    found: list[str] = []
    for ace in re.findall(r"\(([^()]*)\)", sddl):
        parts = ace.split(";")
        if len(parts) < 6 or parts[0] not in ("A", "OA"):
            continue
        name = SHARED_GROUPS.get(parts[5].upper() if len(parts[5]) == 2 else parts[5])
        if name and name not in found:
            found.append(name)
    return found


def folder_access(path: Path) -> tuple[str, str]:
    """("private" | "shared" | "unknown", a sentence saying why), read from
    the folder's (or file's) real permissions. Changes nothing."""
    path = Path(path)
    if not path.exists():
        return "unknown", f"{path} does not exist yet"
    if os.name != "nt":
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            return "shared", f"Other accounts can open it (permissions {mode:o})"
        return "private", "Only its owner can open it"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "acl.txt"
        try:
            done = subprocess.run(
                ["icacls", str(path), "/save", str(saved)],
                check=False,
                capture_output=True,
                timeout=30,
                creationflags=NO_WINDOW,
            )
            text = saved.read_bytes().decode("utf-16", errors="replace") if saved.is_file() else ""
        except (OSError, subprocess.SubprocessError) as exc:
            return "unknown", f"Its permissions could not be read: {exc}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if done.returncode != 0 or len(lines) < 2:
        return "unknown", f"Its permissions could not be read (icacls exit {done.returncode})"
    shared = shared_groups_in_sddl(lines[1])
    if shared:
        return "shared", f"Other accounts on this PC can open it: {', '.join(shared)}"
    return "private", "Only SYSTEM, Administrators and the agent's account can open it"


def _restrict_file(path: Path) -> str | None:
    """Make a secrets file readable only by SYSTEM, Administrators and this
    account. Returns why that failed, or None when it worked."""
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        try:
            done = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    "SYSTEM:F",
                    "/grant:r",
                    "Administrators:F",
                    *(["/grant:r", f"{user}:F"] if user else []),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"icacls couldn't run: {exc}"
        if done.returncode != 0:
            said = (done.stderr or done.stdout or "").strip()
            return f"icacls exit {done.returncode}" + (f": {said}" if said else "")
        return None
    try:
        path.chmod(0o600)
    except OSError as exc:
        return f"chmod failed: {exc}"
    return None


# ----------------------------------------------------------------------
# Tailscale-issued certificates
# ----------------------------------------------------------------------
def request_tailscale_certificate(dns_name: str, cert_dir: Path) -> dict[str, Any]:
    """Ask Tailscale for a publicly trusted certificate for this node.

    Returns a report. It never raises for an ordinary failure, because falling
    back to the local CA is a normal outcome, not an error.
    """
    binary = tailscale.tailscale_binary()
    report: dict[str, Any] = {
        "strategy": "tailscale",
        "ok": False,
        "error": None,
        "cert_path": None,
        "key_path": None,
    }
    if not binary:
        report["error"] = "The tailscale command was not found"
        return report
    secure_directory(cert_dir)
    cert_path = cert_dir / f"{dns_name}.crt"
    key_path = cert_dir / f"{dns_name}.key"
    try:
        proc = subprocess.run(
            [binary, "cert", "--cert-file", str(cert_path), "--key-file", str(key_path), dns_name],
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report["error"] = f"tailscale cert failed to run: {exc}"
        return report
    if proc.returncode != 0:
        report["error"] = (
            proc.stderr or proc.stdout or "tailscale cert returned an error"
        ).strip()[:500]
        return report
    if not cert_path.is_file() or not key_path.is_file():
        report["error"] = "tailscale cert reported success but the files were not written"
        return report
    _restrict_file(key_path)
    report.update(ok=True, cert_path=str(cert_path), key_path=str(key_path))
    return report


# ----------------------------------------------------------------------
# Local CA
# ----------------------------------------------------------------------
def _name(common_name: str, organisation: str = "Minecraft Server Control") -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organisation),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def create_ca(
    cert_dir: Path,
    common_name: str = "Minecraft Server Control local CA",
    valid_days: int = CA_VALID_DAYS,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Create the local CA, or return the existing one.

    The CA is only regenerated when you explicitly ask for it, because
    replacing it means re-trusting it on every device.
    """
    secure_directory(cert_dir)
    ca_cert_path = cert_dir / "ca.crt"
    ca_key_path = cert_dir / "ca.key"
    if ca_cert_path.is_file() and ca_key_path.is_file() and not overwrite:
        return ca_cert_path, ca_key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    now = dt.datetime.now(dt.UTC)
    subject = _name(common_name)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca_cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _restrict_file(ca_key_path)
    return ca_cert_path, ca_key_path


def issue_server_certificate(
    cert_dir: Path,
    hostnames: list[str],
    ip_addresses: list[str],
    valid_days: int = LEAF_VALID_DAYS,
    file_stem: str = "agent",
) -> dict[str, Any]:
    """Issue a server certificate signed by the local CA.

    Every name the dashboard might be opened with must be in the SAN list, or
    the browser will refuse it no matter what the Common Name says.
    """
    if not hostnames and not ip_addresses:
        raise CertificateError("At least one hostname or IP address is required")
    ca_cert_path, ca_key_path = create_ca(cert_dir)
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    alt_names: list[x509.GeneralName] = [x509.DNSName(h) for h in dict.fromkeys(hostnames)]
    for address in dict.fromkeys(ip_addresses):
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            continue
    if not alt_names:
        raise CertificateError("No usable hostname or IP address was supplied")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    common_name = hostnames[0] if hostnames else ip_addresses[0]
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=valid_days))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ObjectIdentifier("1.3.6.1.5.5.7.3.1")]),  # serverAuth
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
    )
    cert_path = cert_dir / f"{file_stem}.crt"
    key_path = cert_dir / f"{file_stem}.key"
    # The chain the agent serves: leaf first, then the CA, so a device that
    # already trusts the CA needs nothing else.
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert_path.read_bytes())
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _restrict_file(key_path)
    return {
        "strategy": "local_ca",
        "ok": True,
        "cert_path": str(cert_path),
        "key_path": str(key_path),
        "ca_path": str(ca_cert_path),
        "hostnames": hostnames,
        "ip_addresses": ip_addresses,
        "valid_days": valid_days,
    }


# ----------------------------------------------------------------------
def local_hostnames() -> list[str]:
    names = []
    try:
        names.append(socket.gethostname())
    except OSError:  # pragma: no cover
        pass
    names.append("localhost")
    return list(dict.fromkeys(n for n in names if n))


def provision(
    cert_dir: Path,
    extra_hostnames: list[str] | None = None,
    extra_ips: list[str] | None = None,
    prefer_tailscale: bool = True,
) -> dict[str, Any]:
    """Get a usable certificate, preferring Tailscale, falling back to the CA.

    Returns a report describing what was actually done, including why
    Tailscale was not used when that is the case.
    """
    report: dict[str, Any] = {"tailscale": None, "result": None}
    status = tailscale.tailscale_status()
    report["tailscale"] = status

    if prefer_tailscale and status.get("connected") and status.get("dns_name"):
        attempt = request_tailscale_certificate(status["dns_name"], cert_dir)
        report["result"] = attempt
        if attempt["ok"]:
            attempt["hostnames"] = [status["dns_name"]]
            attempt["ca_path"] = None  # publicly trusted, nothing to install
            return report
        # fall through to the local CA, keeping the reason visible
        report["tailscale_error"] = attempt["error"]

    # Order matters: the first name becomes the Common Name and the URL this
    # tool tells you to use. An explicitly supplied name wins, then the tailnet
    # name, then whatever this machine calls itself.
    hostnames = list(extra_hostnames or [])
    if status.get("dns_name"):
        hostnames.append(status["dns_name"])
        if status.get("hostname"):
            hostnames.append(status["hostname"])
    hostnames += local_hostnames()
    ips = list(extra_ips or []) + list(status.get("addresses") or []) + ["127.0.0.1"]
    report["result"] = issue_server_certificate(
        cert_dir, [h for h in dict.fromkeys(hostnames) if h], list(dict.fromkeys(ips))
    )
    return report
