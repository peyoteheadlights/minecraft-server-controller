"""Tailscale: what the local Tailscale client says about this machine.

Used by the health checks, the diagnostics, the security page and setup.
Every answer comes from the Tailscale CLI or, failing that, from the network
interfaces, and says which; nothing is assumed.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import psutil

from .winproc import NO_WINDOW


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


def connection_status() -> dict[str, Any]:
    """Report Tailscale state from an actual source.

    Source of truth, in order:
      1. `tailscale status --json` - the daemon's own view of whether it is
         connected. This is the only thing that proves connectivity.
      2. A network interface in the 100.64.0.0/10 range - proves an address
         is assigned, which is *not* the same as being connected. Reported
         as "interface detected", never as "connected".

    `connected` is True only when the daemon said so, False when it said
    otherwise, and None when we could not ask.
    """
    report = tailscale_status()
    if report.get("cli_found") and report.get("connected") is not None and not report.get("error"):
        return {
            "connected": bool(report["connected"]),
            "verified": True,
            "source": "tailscale status --json",
            "address": (report.get("addresses") or [None])[0],
            "addresses": report.get("addresses") or [],
            "dns_name": report.get("dns_name"),
            "backend_state": report.get("backend_state"),
            "detail": ("Verified through the Tailscale daemon"
                       if report["connected"]
                       else f"Tailscale is installed but not connected "
                            f"({report.get('backend_state')})"),
        }

    # The CLI could not answer. Fall back to looking for an address, and be
    # explicit that this proves less.
    cli_problem = report.get("error") or "the tailscale command was not found"
    try:
        addrs = psutil.net_if_addrs()
    except Exception:  # pragma: no cover
        return {"connected": None, "verified": False, "source": "unavailable",
                "address": None, "addresses": [],
                "detail": f"Could not verify: {cli_problem}, and the network "
                          f"interfaces could not be read either."}
    for name, entries in addrs.items():
        for entry in entries:
            if entry.family != socket.AF_INET or not entry.address:
                continue
            is_ts_name = "tailscale" in name.lower() or name.lower().startswith("ts")
            in_cgnat = False
            if entry.address.startswith("100."):
                try:
                    in_cgnat = 64 <= int(entry.address.split(".")[1]) <= 127
                except (ValueError, IndexError):
                    in_cgnat = False
            if is_ts_name or in_cgnat:
                return {
                    "connected": None,
                    "verified": False,
                    "source": "network interface",
                    "address": entry.address,
                    "addresses": [entry.address],
                    "interface": name,
                    "detail": (f"A Tailscale-style address ({entry.address}) is assigned to "
                               f"interface {name}, but connectivity could not be confirmed "
                               f"because {cli_problem}."),
                }
    return {
        "connected": None,
        "verified": False,
        "source": "network interface",
        "address": None,
        "addresses": [],
        "detail": f"No Tailscale address found on this machine, and {cli_problem}.",
    }
