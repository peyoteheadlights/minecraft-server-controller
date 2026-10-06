"""The "How friends join" card: the addresses friends type into Minecraft.

Only addresses the agent actually read from this PC are shown:

  * on the same home network: the PC's own local (private) IPv4 addresses,
    read from its network adapters, with each adapter's name
  * on Tailscale: the address and name the Tailscale client reports
  * the port: what the server's console said it listens on, else what its
    server.properties sets, else Minecraft's own default, saying which
  * Bedrock players (with crossplay on): the Tailscale address and the UDP
    port Geyser was set up with

Whether the server can be reached from the internet is never guessed: this
app doesn't test it and doesn't open router ports, so it is reported as
not known.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import TYPE_CHECKING, Any

import psutil

from .ports import MINECRAFT_DEFAULT_PORT

if TYPE_CHECKING:
    from .core import ServerContext

# Adapters that belong to virtual machines and containers rather than to
# the home network. Their addresses are still real, so they are listed,
# but marked so the page can put the home network's first.
VIRTUAL_HINTS = (
    "vethernet",
    "virtualbox",
    "vmware",
    "hyper-v",
    "docker",
    "wsl",
    "vboxnet",
    "veth",
    "br-",
)
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def local_addresses() -> list[dict[str, Any]]:
    """Private IPv4 addresses of this PC's network adapters that are up.
    Tailscale's own address, loopback and link-local are left out."""
    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:  # pragma: no cover - psutil reads the OS; reported as none
        return []
    found: list[dict[str, Any]] = []
    for name, entries in addresses.items():
        state = stats.get(name)
        if state is not None and not state.isup:
            continue
        lowered = name.lower()
        if "tailscale" in lowered:
            continue
        for entry in entries:
            if entry.family != socket.AF_INET or not entry.address:
                continue
            try:
                ip = ipaddress.ip_address(entry.address)
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local or ip in TAILSCALE_NET or not ip.is_private:
                continue
            found.append(
                {
                    "address": entry.address,
                    "adapter": name,
                    "virtual": any(hint in lowered for hint in VIRTUAL_HINTS),
                }
            )
    found.sort(key=lambda item: (item["virtual"], item["adapter"].lower(), item["address"]))
    return found


def tailscale_address() -> dict[str, Any]:
    from .tailscale import connection_status

    report = connection_status()
    return {
        "address": report.get("address"),
        "dns_name": report.get("dns_name"),
        "connected": report.get("connected"),
        "verified": bool(report.get("verified")),
        "source": report.get("source"),
        "detail": report.get("detail"),
    }


def join_info(ctx: ServerContext) -> dict[str, Any]:
    """Everything the card shows. Asks Tailscale, so call it off the event
    loop."""
    from . import crossplay

    port = ctx.core.ports.port_of(ctx)
    tailscale = tailscale_address()
    bedrock = None
    status = crossplay.status(ctx)
    if status.get("enabled"):
        bedrock_port = ctx.core.ports.bedrock_port_of(ctx)
        bedrock = {
            "port": bedrock_port.port if bedrock_port else None,
            "protocol": "udp",
            "ready": status.get("ready"),
            "address": tailscale["address"],
            "consoles_note": True,
        }
    return {
        "java": {
            "port": port.port,
            "port_source": port.source,
            "default_port": port.port == MINECRAFT_DEFAULT_PORT,
            "local": local_addresses(),
            "tailscale": tailscale,
        },
        "bedrock": bedrock,
        "internet": {
            "known": False,
            "reason": "not_tested",
        },
        "running": ctx.server.running,
    }
