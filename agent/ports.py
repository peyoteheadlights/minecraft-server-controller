"""The port manager: one place that knows which ports the servers use.

Minecraft Java servers listen on a TCP port (Bedrock and Geyser, in later
phases, on UDP). This module:

  * reads each server's real game port from its server.properties
  * checks whether a port is really free on this machine by trying to bind it
  * suggests a port that no configured server uses and nothing else holds
  * refuses to start a server whose port or folder collides with another
    running server, naming that server
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import AgentCore, ServerContext

# What Minecraft itself uses when server.properties does not set a port.
MINECRAFT_DEFAULT_PORT = 25565
SUGGEST_RANGE = 200


@dataclass(frozen=True)
class GamePort:
    port: int
    protocol: str
    source: str  # where the number came from, for the dashboard

    def to_dict(self) -> dict[str, Any]:
        return {"port": self.port, "protocol": self.protocol, "source": self.source}


def read_properties_port(server_dir: Path) -> int | None:
    """server-port from server.properties, or None if it is not set there."""
    path = Path(server_dir) / "server.properties"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "server-port":
            try:
                port = int(value.strip())
            except ValueError:
                return None
            return port if 0 < port < 65536 else None
    return None


def game_port(server_dir: Path, detected: int | None = None) -> GamePort:
    """The TCP port this Java server listens on (or will listen on)."""
    if detected:
        return GamePort(detected, "tcp", "server console")
    configured = read_properties_port(server_dir)
    if configured is not None:
        return GamePort(configured, "tcp", "server.properties")
    return GamePort(
        MINECRAFT_DEFAULT_PORT, "tcp", "Minecraft's default (server.properties does not set one)"
    )


def is_free(port: int, protocol: str = "tcp", host: str = "0.0.0.0") -> bool:
    """True when nothing on this machine holds the port. Checked by binding
    it, which is the only reliable test; the socket is closed at once."""
    kind = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
    sock = socket.socket(socket.AF_INET, kind)
    try:
        if os.name == "nt":
            # Without this Windows lets a second socket share the port.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _same_or_nested(a: Path, b: Path) -> bool:
    try:
        a, b = a.resolve(), b.resolve()
    except OSError:
        return False
    return a == b or a in b.parents or b in a.parents


class PortManager:
    def __init__(self, core: AgentCore):
        self.core = core

    def port_of(self, ctx: ServerContext) -> GamePort:
        return game_port(ctx.config.server_dir, ctx.server.detected_port)

    def used(self, exclude: str | None = None) -> dict[tuple[str, int], str]:
        """(protocol, port) -> server id, for every configured server."""
        taken: dict[tuple[str, int], str] = {}
        for server_id, ctx in self.core.servers.items():
            if server_id == exclude:
                continue
            port = self.port_of(ctx)
            taken.setdefault((port.protocol, port.port), server_id)
        return taken

    def suggest(self, protocol: str = "tcp", start: int = MINECRAFT_DEFAULT_PORT) -> int | None:
        """The first port from ``start`` that no server uses and is free here."""
        taken = self.used()
        for port in range(start, min(start + SUGGEST_RANGE, 65536)):
            if (protocol, port) in taken:
                continue
            if is_free(port, protocol):
                return port
        return None

    def start_conflicts(self, ctx: ServerContext) -> list[str]:
        """Reasons this server must not start now because of another one."""
        problems = []
        mine = self.port_of(ctx)
        for other in self.core.servers.values():
            if other is ctx or not other.server.running:
                continue
            theirs = self.port_of(other)
            if (theirs.protocol, theirs.port) == (mine.protocol, mine.port):
                problems.append(
                    f"Port {mine.port} is already used by the running server "
                    f"'{other.name}'. Change server-port in this server's "
                    "server.properties, or stop the other server first."
                )
            if _same_or_nested(ctx.config.server_dir, other.config.server_dir):
                problems.append(
                    f"The folder {ctx.config.server_dir} is already used by the running "
                    f"server '{other.name}'. Two servers cannot run from the same folder."
                )
        return problems

    def start_warnings(self, ctx: ServerContext) -> list[str]:
        mine = self.port_of(ctx)
        if not is_free(mine.port, mine.protocol):
            return [
                f"Port {mine.port} looks busy on this PC (another program may be using it), "
                "so Minecraft may fail to start."
            ]
        return []
