"""TLS certificate inspection.

Every value here comes from actually parsing the certificate and key files on
disk. Nothing is assumed: if a file cannot be read or parsed, the field is
reported as unknown with the reason, never as "valid".

Private key material never leaves this module. `CertificateInfo` deliberately
carries no key bytes, so no API response, log line or template can leak it -
the only thing recorded about the key is whether its public half matches the
certificate.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import socket
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("msc.tls")

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - cryptography is a hard requirement
    HAVE_CRYPTOGRAPHY = False

WARN_DAYS = 14
CRITICAL_DAYS = 3


@dataclass
class CertificateInfo:
    """What we were able to verify about a certificate. Unknown stays unknown."""

    certificate_path: str = ""
    key_path: str = ""
    certificate_present: bool | None = None
    key_present: bool | None = None
    parsed: bool = False
    parse_error: str | None = None
    subject: str | None = None
    issuer: str | None = None
    self_signed: bool | None = None
    not_before: float | None = None
    not_after: float | None = None
    days_remaining: float | None = None
    expired: bool | None = None
    names: list[str] = field(default_factory=list)
    ip_names: list[str] = field(default_factory=list)
    key_matches_certificate: bool | None = None
    key_check_error: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def expiry_severity(self) -> str:
        """critical | warn | ok | unknown - never guessed."""
        if self.days_remaining is None:
            return "unknown"
        if self.days_remaining <= 0:
            return "critical"
        if self.days_remaining <= CRITICAL_DAYS:
            return "critical"
        if self.days_remaining <= WARN_DAYS:
            return "warn"
        return "ok"

    def covers(self, hostname: str) -> bool | None:
        """Does this certificate cover `hostname`?

        Returns None when the answer cannot be determined (certificate not
        parsed, or no hostname to check against).
        """
        if not self.parsed or not hostname:
            return None
        host = hostname.strip().lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
            return host in [ip.lower() for ip in self.ip_names]
        except ValueError:
            pass
        for name in self.names:
            candidate = name.lower().rstrip(".")
            if candidate == host:
                return True
            if candidate.startswith("*."):
                # a wildcard matches exactly one label
                suffix = candidate[1:]
                if host.endswith(suffix) and host.count(".") == candidate.count("."):
                    return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "certificate_path": self.certificate_path,
            "key_path": self.key_path,
            "certificate_present": self.certificate_present,
            "key_present": self.key_present,
            "parsed": self.parsed,
            "parse_error": self.parse_error,
            "subject": self.subject,
            "issuer": self.issuer,
            "self_signed": self.self_signed,
            "not_before": self.not_before,
            "not_after": self.not_after,
            "days_remaining": self.days_remaining,
            "expired": self.expired,
            "names": self.names,
            "ip_names": self.ip_names,
            "key_matches_certificate": self.key_matches_certificate,
            "key_check_error": self.key_check_error,
            "expiry_severity": self.expiry_severity,
            "problems": self.problems,
        }


def _utc_timestamp(value: dt.datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.timestamp()


def inspect_certificate(
    cert_path: str | Path | None, key_path: str | Path | None = None, now: float | None = None
) -> CertificateInfo:
    """Read a certificate (and optionally its key) and report what is true.

    Source of truth: the PEM files on disk. Nothing is inferred from the
    configuration.
    """
    info = CertificateInfo(
        certificate_path=str(cert_path or ""),
        key_path=str(key_path or ""),
    )
    if not cert_path:
        info.certificate_present = False
        info.problems.append("No certificate path is configured")
        return info
    cert_file = Path(cert_path)
    info.certificate_present = cert_file.is_file()
    if not info.certificate_present:
        info.problems.append(f"The certificate file isn't there: {cert_file}")
        return info
    if key_path:
        info.key_present = Path(key_path).is_file()
        if not info.key_present:
            info.problems.append(f"The private key file isn't there: {key_path}")

    if not HAVE_CRYPTOGRAPHY:  # pragma: no cover
        info.parse_error = (
            "The 'cryptography' package is not installed, so the certificate could not be parsed"
        )
        info.problems.append(info.parse_error)
        return info

    try:
        pem = cert_file.read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
    except (OSError, ValueError) as exc:
        info.parse_error = f"The certificate could not be parsed: {exc}"
        info.problems.append(info.parse_error)
        return info

    info.parsed = True
    try:
        info.subject = cert.subject.rfc4514_string()
        info.issuer = cert.issuer.rfc4514_string()
        info.self_signed = cert.subject == cert.issuer
    except Exception:  # pragma: no cover
        pass

    try:
        not_before = _utc_timestamp(cert.not_valid_before_utc)
        not_after = _utc_timestamp(cert.not_valid_after_utc)
    except AttributeError:  # pragma: no cover - older cryptography
        not_before = _utc_timestamp(cert.not_valid_before)
        not_after = _utc_timestamp(cert.not_valid_after)
    info.not_before = not_before
    info.not_after = not_after
    reference = now if now is not None else dt.datetime.now(dt.UTC).timestamp()
    info.days_remaining = (not_after - reference) / 86400
    info.expired = reference > not_after or reference < not_before
    if reference < not_before:
        info.problems.append("The certificate isn't valid yet: its start date is in the future.")
    if reference > not_after:
        info.problems.append("The certificate has expired")

    # Subject Alternative Names are what browsers actually check.
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        info.names = [str(n) for n in san.get_values_for_type(x509.DNSName)]
        info.ip_names = [str(n) for n in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        info.problems.append(
            "The certificate has no Subject Alternative Name extension. "
            "Modern browsers reject such certificates regardless of the Common Name."
        )
        try:
            common = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if common:
                info.names = [str(common[0].value)]
        except Exception:  # pragma: no cover
            pass

    if key_path and info.key_present:
        info.key_matches_certificate, info.key_check_error = _key_matches(Path(key_path), cert)
        if info.key_matches_certificate is False:
            info.problems.append("The private key doesn't belong to this certificate.")
    return info


def _key_matches(key_file: Path, cert) -> tuple[bool | None, str | None]:
    """Compare the key's public half with the certificate's public key.

    Only public key bytes are ever compared or returned; the private key is
    loaded, used and dropped.
    """
    try:
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    except TypeError:
        return None, "The private key is encrypted with a passphrase, so it could not be checked"
    except (OSError, ValueError) as exc:
        return None, f"The private key could not be read: {exc}"
    try:
        key_public = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        cert_public = cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return key_public == cert_public, None
    except Exception as exc:  # pragma: no cover
        return None, f"The key could not be compared with the certificate: {exc}"
    finally:
        del key


def verify_endpoint(
    host: str,
    port: int,
    ca_file: str | Path | None = None,
    server_hostname: str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Actually complete a TLS handshake against the running agent.

    This is the only honest way to say "HTTPS works". Certificate verification
    is always on; when a private CA is in use its bundle is supplied, rather
    than verification being switched off.
    """
    result: dict[str, Any] = {
        "reachable": None,
        "handshake": None,
        "verified": None,
        "protocol": None,
        "cipher": None,
        "error": None,
        "hostname_checked": server_hostname or host,
    }
    context = ssl.create_default_context()
    if ca_file and Path(ca_file).is_file():
        try:
            context.load_verify_locations(cafile=str(ca_file))
        except (OSError, ssl.SSLError) as exc:
            result["error"] = f"The CA bundle could not be loaded: {exc}"
            return result
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            result["reachable"] = True
            with context.wrap_socket(raw, server_hostname=server_hostname or host) as tls:
                result["handshake"] = True
                result["verified"] = True
                result["protocol"] = tls.version()
                cipher = tls.cipher()
                result["cipher"] = cipher[0] if cipher else None
    except ssl.SSLCertVerificationError as exc:
        result["handshake"] = True
        result["verified"] = False
        result["error"] = f"The certificate was not trusted: {exc.verify_message or exc}"
    except ssl.SSLError as exc:
        result["reachable"] = True
        result["handshake"] = False
        result["error"] = f"The TLS handshake failed: {exc}"
    except OSError as exc:
        result["reachable"] = False
        result["error"] = f"The endpoint could not be reached: {exc}"
    return result


def fingerprint(cert_path: str | Path) -> str | None:
    """SHA-256 fingerprint, for confirming the CA you trusted is the right one."""
    if not HAVE_CRYPTOGRAPHY:  # pragma: no cover
        return None
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        return cert.fingerprint(hashes.SHA256()).hex(":").upper()
    except (OSError, ValueError):
        return None
