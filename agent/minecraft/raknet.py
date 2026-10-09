"""Asking a Bedrock server whether it is there: RakNet's unconnected ping.

Bedrock servers speak RakNet over UDP, so a TCP connect says nothing about
them (UDP has no connection to make). Instead the agent sends the same
"unconnected ping" a Bedrock game sends to list a server, and counts the
server as listening only when an "unconnected pong" comes back. The pong's
own status text (MCPE;name;protocol;version;players;max;...) is returned
as it was sent, never filled in.
"""

from __future__ import annotations

import os
import socket
import struct
import time
from typing import Any

# RakNet's "offline message" marker, the same in every unconnected packet.
MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")
UNCONNECTED_PING = 0x01
UNCONNECTED_PONG = 0x1C


def ping_packet(client_guid: int | None = None) -> bytes:
    guid = client_guid if client_guid is not None else int.from_bytes(os.urandom(8), "big")
    now = int(time.monotonic() * 1000) & 0x7FFFFFFFFFFFFFFF
    return struct.pack(">BQ", UNCONNECTED_PING, now) + MAGIC + struct.pack(">Q", guid)


def parse_pong(data: bytes) -> dict[str, Any] | None:
    """The pong's fields, or None when ``data`` isn't an unconnected pong."""
    if len(data) < 35 or data[0] != UNCONNECTED_PONG or data[17:33] != MAGIC:
        return None
    (length,) = struct.unpack(">H", data[33:35])
    text = data[35 : 35 + length].decode("utf-8", errors="replace")
    parts = text.split(";")
    return {
        "status": text,
        "edition": parts[0] if parts else None,
        "name": parts[1] if len(parts) > 1 else None,
        "version": parts[3] if len(parts) > 3 else None,
        "players": int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None,
        "max_players": int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else None,
    }


def ping(host: str, port: int, timeout: float = 1.5) -> dict[str, Any] | None:
    """Send an unconnected ping and wait for the pong. None: no answer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(ping_packet(), (host, int(port)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(2048)
            except (TimeoutError, OSError):
                return None
            answer = parse_pong(data)
            if answer is not None:
                return answer
        return None
    finally:
        sock.close()
