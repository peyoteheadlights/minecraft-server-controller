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
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from cryptography import x509

from ..winproc import NO_WINDOW
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CA_VALID_DAYS = 3650      # the CA you trust once
LEAF_VALID_DAYS = 398     # the maximum browsers accept for a server certificate


class CertificateError(RuntimeError):
    pass


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def secure_directory(path: Path) -> Path:
    """Create a directory that only the current user can read.

    On Windows the inherited ACL is replaced so that only SYSTEM, the
    Administrators group and the current user have access - the private key
    lives here.
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", "SYSTEM:(OI)(CI)F",
                 "/grant:r", "Administrators:(OI)(CI)F",
                 *(["/grant:r", f"{user}:(OI)(CI)F"] if user else [])],
                check=False, capture_output=True, timeout=30, creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


def _restrict_file(path: Path) -> None:
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", "SYSTEM:F", "/grant:r", "Administrators:F",
                 *(["/grant:r", f"{user}:F"] if user else [])],
                check=False, capture_output=True, timeout=30, creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            path.chmod(0o600)
        except OSError:
            pass


# ----------------------------------------------------------------------
# Tailscale
# ----------------------------------------------------------------------
def tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        "/usr/bin/tailscale", "/usr/local/bin/tailscale",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def tailscale_status() -> dict[str, Any]:
    """Ask the Tailscale CLI what it actually knows.

    Source of truth: `tailscale status --json`. If the CLI is missing or the
    call fails, every field stays unknown rather than being guessed.
    """
    result: dict[str, Any] = {
        "cli_found": False, "binary": None, "backend_state": None,
        "connected": None, "dns_name": None, "hostname": None,
        "addresses": [], "magicdns": None, "https_available": None,
        "tailnet": None, "error": None,
    }
    binary = tailscale_binary()
    if not binary:
        result["error"] = "The tailscale command was not found on this machine"
        return result
    result["cli_found"] = True
    result["binary"] = binary
    try:
        proc = subprocess.run([binary, "status", "--json"],
                              capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = f"tailscale status failed: {exc}"
        return result
    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout or "tailscale status returned an error").strip()[:300]
        return result
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        result["error"] = f"tailscale status returned output that could not be read: {exc}"
        return result

    result["backend_state"] = data.get("BackendState")
    result["connected"] = data.get("BackendState") == "Running"
    self_node = data.get("Self") or {}
    dns_name = (self_node.get("DNSName") or "").rstrip(".")
    result["dns_name"] = dns_name or None
    result["hostname"] = self_node.get("HostName")
    result["addresses"] = list(self_node.get("TailscaleIPs") or [])
    result["magicdns"] = bool(dns_name)
    if dns_name and "." in dns_name:
        result["tailnet"] = dns_name.split(".", 1)[1]
    caps = self_node.get("CapMap") or {}
    if isinstance(caps, dict) and caps:
        result["https_available"] = "https" in " ".join(caps.keys()).lower()
    return result


def request_tailscale_certificate(dns_name: str, cert_dir: Path) -> dict[str, Any]:
    """Ask Tailscale for a publicly trusted certificate for this node.

    Returns a report. It never raises for an ordinary failure, because falling
    back to the local CA is a normal outcome, not an error.
    """
    binary = tailscale_binary()
    report: dict[str, Any] = {"strategy": "tailscale", "ok": False, "error": None,
                              "cert_path": None, "key_path": None}
    if not binary:
        report["error"] = "The tailscale command was not found"
        return report
    secure_directory(cert_dir)
    cert_path = cert_dir / f"{dns_name}.crt"
    key_path = cert_dir / f"{dns_name}.key"
    try:
        proc = subprocess.run(
            [binary, "cert", "--cert-file", str(cert_path), "--key-file", str(key_path), dns_name],
            capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report["error"] = f"tailscale cert failed to run: {exc}"
        return report
    if proc.returncode != 0:
        report["error"] = (proc.stderr or proc.stdout or "tailscale cert returned an error").strip()[:500]
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
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organisation),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def create_ca(cert_dir: Path, common_name: str = "Minecraft Server Control local CA",
              valid_days: int = CA_VALID_DAYS, overwrite: bool = False) -> tuple[Path, Path]:
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
    now = dt.datetime.now(dt.timezone.utc)
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
            x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                          content_commitment=False, key_encipherment=False,
                          data_encipherment=False, key_agreement=False,
                          encipher_only=False, decipher_only=False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca_cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    _restrict_file(ca_key_path)
    return ca_cert_path, ca_key_path


def issue_server_certificate(cert_dir: Path, hostnames: list[str], ip_addresses: list[str],
                             valid_days: int = LEAF_VALID_DAYS,
                             file_stem: str = "agent") -> dict[str, Any]:
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
    now = dt.datetime.now(dt.timezone.utc)
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
            x509.KeyUsage(digital_signature=True, key_encipherment=True,
                          content_commitment=False, data_encipherment=False,
                          key_agreement=False, key_cert_sign=False, crl_sign=False,
                          encipher_only=False, decipher_only=False),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ObjectIdentifier("1.3.6.1.5.5.7.3.1")]),  # serverAuth
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    cert_path = cert_dir / f"{file_stem}.crt"
    key_path = cert_dir / f"{file_stem}.key"
    # The chain the agent serves: leaf first, then the CA, so a device that
    # already trusts the CA needs nothing else.
    cert_path.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM) + ca_cert_path.read_bytes()
    )
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
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


def provision(cert_dir: Path, extra_hostnames: list[str] | None = None,
              extra_ips: list[str] | None = None,
              prefer_tailscale: bool = True) -> dict[str, Any]:
    """Get a usable certificate, preferring Tailscale, falling back to the CA.

    Returns a report describing what was actually done, including why
    Tailscale was not used when that is the case.
    """
    report: dict[str, Any] = {"tailscale": None, "result": None}
    status = tailscale_status()
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
