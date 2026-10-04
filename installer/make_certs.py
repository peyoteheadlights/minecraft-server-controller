"""Provision the HTTPS certificate for the agent.

    python -m installer.make_certs              # pick the best strategy
    python -m installer.make_certs --renew      # re-issue, keeping the same CA
    python -m installer.make_certs --local-ca   # skip Tailscale, use the local CA
    python -m installer.make_certs --host name  # add an extra hostname to the certificate
    python -m installer.make_certs --show       # report on the current certificate

It writes the certificate and key into the agent's data folder, updates
config.yaml to point at them, and prints exactly what to trust on each device.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.security.certs import (  # noqa: E402
    issue_server_certificate,
    local_hostnames,
    provision,
    secure_directory,
    tailscale_status,
)
from agent.security.tls import fingerprint, inspect_certificate  # noqa: E402


def show(config: Config) -> int:
    info = inspect_certificate(config.tls_certificate, config.tls_private_key)
    print("\nCurrent certificate")
    print("-" * 56)
    print(f"  Certificate file : {info.certificate_path}")
    print(f"  Present          : {info.certificate_present}")
    if not info.parsed:
        print(f"  Parsed           : no ({info.parse_error or 'not present'})")
        return 1
    print(f"  Issuer           : {info.issuer}")
    print(f"  Subject          : {info.subject}")
    print(f"  Covers (DNS)     : {', '.join(info.names) or 'none'}")
    print(f"  Covers (IP)      : {', '.join(info.ip_names) or 'none'}")
    print(f"  Expires in       : {info.days_remaining:.0f} days ({info.expiry_severity})")
    print(f"  Key matches cert : {info.key_matches_certificate}")
    ca = config.tls_ca_certificate
    if ca:
        print(f"  Local CA         : {ca}")
        print(f"  CA fingerprint   : {fingerprint(ca)}")
    else:
        print("  Local CA         : none (publicly trusted certificate)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the agent's HTTPS certificate")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--renew", action="store_true", help="Re-issue, keeping the existing CA")
    parser.add_argument("--local-ca", action="store_true", help="Do not try Tailscale")
    parser.add_argument("--host", action="append", default=[],
                        help="Extra hostname for the certificate (repeatable)")
    parser.add_argument("--ip", action="append", default=[],
                        help="Extra IP address for the certificate (repeatable)")
    parser.add_argument("--show", action="store_true", help="Report on the current certificate")
    args = parser.parse_args(argv)

    config = Config.load(args.config)
    config.ensure_dirs()
    cert_dir = secure_directory(config.cert_dir)

    if args.show:
        return show(config)

    print("Minecraft Server Control - HTTPS certificate setup")
    print("=" * 56)

    status = tailscale_status()
    if status["cli_found"]:
        print(f"  Tailscale CLI    : {status['binary']}")
        print(f"  Backend state    : {status.get('backend_state') or 'unknown'}")
        print(f"  MagicDNS name    : {status.get('dns_name') or 'not available'}")
        print(f"  Tailscale IPs    : {', '.join(status.get('addresses') or []) or 'none'}")
    else:
        print(f"  Tailscale CLI    : not found ({status.get('error')})")

    report = provision(cert_dir, extra_hostnames=args.host, extra_ips=args.ip,
                       prefer_tailscale=not args.local_ca)
    result = report["result"]

    if report.get("tailscale_error"):
        print(f"\n  Tailscale certificate was not used: {report['tailscale_error']}")
        print("  Falling back to the local certificate authority.")

    print()
    if result["strategy"] == "tailscale":
        hostname = result["hostnames"][0]
        print("Strategy: Tailscale-issued certificate (publicly trusted)")
        print("-" * 56)
        print(f"  Certificate : {result['cert_path']}")
        print(f"  Private key : {result['key_path']}")
        print(f"  Hostname    : {hostname}")
        print("\n  Nothing to install on your PC or phone: this certificate is signed by")
        print("  Let's Encrypt, which every browser already trusts.")
        print("  Tailscale renews it automatically. Re-run this command after a renewal,")
        print("  or let the agent's scheduled renewal task do it.")
        config.set("tls.hostname", hostname)
        config.set("tls.ca_certificate", "")
    else:
        hostname = result["hostnames"][0] if result["hostnames"] else result["ip_addresses"][0]
        ca_path = result["ca_path"]
        print("Strategy: local certificate authority")
        print("-" * 56)
        print(f"  CA certificate : {ca_path}")
        print(f"  CA fingerprint : {fingerprint(ca_path)}")
        print(f"  Certificate    : {result['cert_path']}")
        print(f"  Private key    : {result['key_path']}")
        print(f"  Valid for      : {result['valid_days']} days")
        print(f"  Covers         : {', '.join(result['hostnames'] + result['ip_addresses'])}")
        print()
        print("  Trust the CA once on each device, then no browser warnings ever again:")
        print()
        print("  Windows (Administrator PowerShell):")
        print(f'    Import-Certificate -FilePath "{ca_path}" '
              r'-CertStoreLocation Cert:\LocalMachine\Root')
        print()
        print("  Android: copy ca.crt to the phone, then Settings -> Security ->")
        print("           Encryption & credentials -> Install a certificate -> CA certificate")
        print()
        print("  iOS/iPadOS: AirDrop or email ca.crt to the device, open it, then")
        print("           Settings -> Profile Downloaded -> Install, and then")
        print("           Settings -> General -> About -> Certificate Trust Settings ->")
        print("           enable full trust for this CA")
        print()
        print("  Keep ca.key private and never copy it to another device. Only ca.crt")
        print("  is installed anywhere.")
        config.set("tls.hostname", hostname)
        config.set("tls.ca_certificate", "certs/ca.crt")

    config.set("tls.enabled", True)
    config.set("tls.certificate", str(Path(result["cert_path"])))
    config.set("tls.private_key", str(Path(result["key_path"])))
    saved = config.save()

    info = inspect_certificate(result["cert_path"], result["key_path"])
    print()
    print("Verification (read back from the files that were just written)")
    print("-" * 56)
    print(f"  Parsed            : {info.parsed}")
    print(f"  Key matches cert  : {info.key_matches_certificate}")
    print(f"  Expires in        : "
          f"{f'{info.days_remaining:.0f} days' if info.days_remaining is not None else 'unknown'}")
    print(f"  Covers {hostname:<11}: {info.covers(hostname)}")
    print(f"\n  Updated {saved}")
    print(f"  Dashboard URL     : https://{hostname}:{config.network.port}")
    print("\n  Next: set network.host to this machine's Tailscale address in config.yaml,")
    print("        then run: python -m agent.main --check")
    return 0 if info.parsed and info.key_matches_certificate else 1


if __name__ == "__main__":
    raise SystemExit(main())
