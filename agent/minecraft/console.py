"""Parsing of Minecraft server console output, plus a bounded console buffer.

Every server type prints its version and its loader differently, so each
has its own pattern (see LOADER_PATTERNS). Until one of those lines
appears, the version stays unknown: it is never taken from a jar name or
from the type that was chosen.

The buffer is deliberately capped. The browser is only ever served a slice of
it (tail / since / search), so a 40 MB latest.log can never be pushed into a
phone browser.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Vanilla/Fabric line: [12:34:56] [Server thread/INFO]: message
LINE_RE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2}:\d{2})\]\s*\[(?P<thread>[^/\]]+)/(?P<level>[A-Z]+)\]"
    r"\s*(?:\((?P<mod>[^)]*)\)\s*)?:?\s?(?P<msg>.*)$"
)

DONE_RE = re.compile(r'Done \((?P<secs>[0-9.]+)s\)! For help, type "help"')
MC_VERSION_RE = re.compile(r"Starting minecraft server version (?P<ver>[\w.\-]+)")
# Each server type's version-and-loader line, as the real servers print it.
# "mc" is the Minecraft version, "loader" the loader or build version, and
# "name" (when matched) the loader's own name.
LOADER_PATTERNS = (
    # Fabric: "Loading Minecraft 1.21.1 with Fabric Loader 0.16.5"
    re.compile(
        r"Loading Minecraft (?P<mc>[\w.\-]+) with (?P<name>Fabric|Quilt) Loader "
        r"(?P<loader>[\w.\-+]+)"
    ),
    # Forge/NeoForge: "ML: javafml, 47.3.0, ..." comes later; the start line is
    # "MinecraftForge v47.3.0 Initialized" / "NeoForge v21.1.9 Initialized"
    re.compile(r"(?P<name>MinecraftForge|NeoForge) v(?P<loader>[\w.\-+]+) Initialized"),
    # Forge's own banner: "Forge Mod Loader version 47.3.0 for Minecraft 1.20.1"
    re.compile(
        r"(?P<name>Forge|NeoForge) Mod Loader version (?P<loader>[\w.\-+]+) "
        r"for Minecraft (?P<mc>[\w.\-]+)"
    ),
    # Forge and NeoForge, early in the log:
    # "Forge mod loading, version 47.3.0, for MC 1.20.1 with MCP 20230612.114412"
    re.compile(
        r"(?P<name>Forge|NeoForge) mod loading, version (?P<loader>[\w.\-+]+), "
        r"for MC (?P<mc>[\w.\-]+)"
    ),
    # Paper/Purpur: "This server is running Paper version 1.21.1-129-main@... (MC: 1.21.1)"
    re.compile(
        r"This server is running (?P<name>Paper|Purpur)[\w\s]*? version "
        r"(?P<loader>[^\s(]+).*?\(MC: (?P<mc>[\w.\-]+)\)"
    ),
    # Newer Paper leaves the "(MC: ...)" off: "This server is running Paper
    # version 1.21.4-232-ver/1.21.4@12ff3e3 (2025-03-12...) (Implementing API
    # version 1.21.4-R0.1-SNAPSHOT)". The Minecraft version then comes from
    # Minecraft's own "Starting minecraft server version" line.
    re.compile(
        r"This server is running (?P<name>Paper|Purpur)[\w\s]*? version (?P<loader>[^\s(]+)"
    ),
)
LOADER_NAMES = {
    "fabric": "Fabric Loader",
    "quilt": "Quilt Loader",
    "minecraftforge": "Forge",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "paper": "Paper",
    "purpur": "Purpur",
}
# A player name, with Floodgate's prefix for a Bedrock player ("." by
# default) allowed in front of it. The name is always shown as printed.
PLAYER = r"\.?[A-Za-z0-9_]{1,16}"
JOIN_RE = re.compile(rf"(?P<name>{PLAYER})(?:\[[^\]]*\])? joined the game")
LEAVE_RE = re.compile(rf"(?P<name>{PLAYER}) left the game")
UUID_RE = re.compile(rf"UUID of player (?P<name>{PLAYER}) is (?P<uuid>[0-9a-fA-F-]{{32,36}})")
STOPPING_RE = re.compile(r"(Stopping the server|Stopping server|Saving worlds|Server closed)")
PORT_RE = re.compile(r"Starting Minecraft server on (?P<host>[^:\s]*):(?P<port>\d+)")
MODS_LOADED_RE = re.compile(r"Loading (?P<count>\d+) mods:")
# Forge and NeoForge: "Found 23 mod files" / Paper: "Loaded 4 plugins"
CONTENT_COUNT_RES = (
    re.compile(r"Found (?P<count>\d+) mod file"),
    re.compile(r"Loading (?P<count>\d+) plugin"),
    re.compile(r"Loaded (?P<count>\d+) plugin"),
)
# Paper's "tps" answer: "TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0"
EULA_RE = re.compile(r"You need to agree to the EULA in order to run the server", re.IGNORECASE)
PLAYER_LIST_RE = re.compile(
    r"There are (?P<online>\d+) of a max of (?P<max>\d+) players online:\s*(?P<names>.*)"
)

# TPS/MSPT answers differ per mod/server. We support the common shapes and
# report "unknown" instead of inventing a number when nothing answers.
TPS_PATTERNS = [
    re.compile(r"TPS:\s*(?P<tps>[0-9.]+)\s*MSPT:\s*(?P<mspt>[0-9.]+)", re.IGNORECASE),  # Carpet
    re.compile(r"TPS from last[^:]*:\s*\*?(?P<tps>[0-9.]+)", re.IGNORECASE),  # spark
    re.compile(r"\bTPS[:=]\s*\*?(?P<tps>[0-9.]+)", re.IGNORECASE),  # generic
]
# Vanilla `tick query` (1.20.3+) prints the *target* rate, which is a setting,
# not a measurement. It is captured separately and never reported as TPS; the
# measured value comes from "Average time per tick".
TARGET_TPS_RE = re.compile(r"Target tick rate:\s*(?P<target>[0-9.]+) per second", re.IGNORECASE)
UNKNOWN_COMMAND_RE = re.compile(r"Unknown or incomplete command|Unknown command", re.IGNORECASE)

MSPT_PATTERNS = [
    re.compile(r"Average time per tick:\s*(?P<mspt>[0-9.]+)\s*ms", re.IGNORECASE),
    re.compile(r"(?:MSPT|mean tick time)[^0-9]{0,12}(?P<mspt>[0-9.]+)", re.IGNORECASE),
]


@dataclass
class ConsoleLine:
    seq: int
    ts: float
    raw: str
    level: str = "INFO"
    thread: str = ""
    message: str = ""
    source: str = "stdout"  # stdout | agent | command

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "raw": self.raw,
            "level": self.level,
            "thread": self.thread,
            "message": self.message,
            "source": self.source,
        }


def parse_line(raw: str, seq: int, source: str = "stdout") -> ConsoleLine:
    raw = raw.rstrip("\r\n")
    m = LINE_RE.match(raw)
    if m:
        level = m.group("level").upper()
        if level not in {"INFO", "WARN", "ERROR", "DEBUG", "FATAL", "TRACE"}:
            level = "INFO"
        return ConsoleLine(
            seq=seq,
            ts=time.time(),
            raw=raw,
            level=level,
            thread=m.group("thread"),
            message=m.group("msg") or "",
            source=source,
        )
    upper = raw.upper()
    level = "INFO"
    if raw.startswith("\tat ") or "EXCEPTION" in upper or "ERROR" in upper or "CAUSED BY" in upper:
        level = "ERROR"
    elif "WARN" in upper:
        level = "WARN"
    return ConsoleLine(seq=seq, ts=time.time(), raw=raw, level=level, message=raw, source=source)


class ConsoleBuffer:
    def __init__(self, maxlen: int = 2000):
        self._lines: deque[ConsoleLine] = deque(maxlen=maxlen)
        self._seq = 0

    @property
    def maxlen(self) -> int:
        return self._lines.maxlen or 0

    def append(self, raw: str, source: str = "stdout") -> ConsoleLine:
        self._seq += 1
        line = parse_line(raw, self._seq, source)
        self._lines.append(line)
        return line

    def tail(self, count: int = 100) -> list[ConsoleLine]:
        count = max(1, min(int(count), self.maxlen or 2000))
        return list(self._lines)[-count:]

    def since(self, seq: int, limit: int = 500) -> list[ConsoleLine]:
        return [ln for ln in self._lines if ln.seq > seq][-limit:]

    def search(self, needle: str, limit: int = 200, level: str | None = None) -> list[ConsoleLine]:
        needle_l = needle.lower()
        found = [
            ln
            for ln in self._lines
            if needle_l in ln.raw.lower() and (level is None or ln.level == level.upper())
        ]
        return found[-limit:]

    def by_level(self, level: str, limit: int = 100) -> list[ConsoleLine]:
        return [ln for ln in self._lines if ln.level == level.upper()][-limit:]

    def all_raw(self) -> list[str]:
        return [ln.raw for ln in self._lines]

    def clear(self) -> None:
        self._lines.clear()

    def __len__(self) -> int:
        return len(self._lines)


@dataclass
class ParsedSignals:
    """Facts extracted from a single console line."""

    done_seconds: float | None = None
    mc_version: str | None = None
    loader_version: str | None = None
    # The loader's own name as the console printed it ("Fabric Loader",
    # "Paper"), so a server whose type was set wrong can be spotted.
    loader_name: str | None = None
    port: int | None = None
    eula_required: bool = False
    player_joined: str | None = None
    player_left: str | None = None
    player_uuid: tuple[str, str] | None = None
    player_list: tuple[int, int, list[str]] | None = None
    stopping: bool = False
    tps: float | None = None
    mspt: float | None = None
    mod_count: int | None = None
    target_tps: float | None = None
    unknown_command: bool = False
    extras: dict = field(default_factory=dict)


def extract_signals(line: ConsoleLine) -> ParsedSignals:
    sig = ParsedSignals()
    text = line.message or line.raw

    if m := DONE_RE.search(text):
        sig.done_seconds = float(m.group("secs"))
    if m := MC_VERSION_RE.search(text):
        sig.mc_version = m.group("ver")
    for pattern in LOADER_PATTERNS:
        if m := pattern.search(text):
            groups = m.groupdict()
            sig.mc_version = sig.mc_version or groups.get("mc")
            sig.loader_version = groups.get("loader")
            name = (groups.get("name") or "").lower()
            sig.loader_name = LOADER_NAMES.get(name, groups.get("name"))
            break
    if EULA_RE.search(text):
        sig.eula_required = True
    if m := PORT_RE.search(text):
        sig.port = int(m.group("port"))
    if m := UUID_RE.search(text):
        sig.player_uuid = (m.group("name"), m.group("uuid"))
    if m := PLAYER_LIST_RE.search(text):
        names = [n.strip() for n in m.group("names").split(",") if n.strip()]
        sig.player_list = (int(m.group("online")), int(m.group("max")), names)
    elif m := JOIN_RE.search(text):
        sig.player_joined = m.group("name")
    elif m := LEAVE_RE.search(text):
        sig.player_left = m.group("name")
    if STOPPING_RE.search(text):
        sig.stopping = True
    if m := MODS_LOADED_RE.search(text):
        sig.mod_count = int(m.group("count"))
    else:
        for pattern in CONTENT_COUNT_RES:
            if m := pattern.search(text):
                sig.mod_count = int(m.group("count"))
                break

    if m := TARGET_TPS_RE.search(text):
        sig.target_tps = float(m.group("target"))
    if UNKNOWN_COMMAND_RE.search(text):
        sig.unknown_command = True

    for pattern in TPS_PATTERNS:
        if m := pattern.search(text):
            try:
                sig.tps = float(m.group("tps"))
            except (TypeError, ValueError):
                pass
            groups = m.groupdict()
            if groups.get("mspt"):
                sig.mspt = float(groups["mspt"])
            break
    if sig.mspt is None:
        for pattern in MSPT_PATTERNS:
            if m := pattern.search(text):
                try:
                    sig.mspt = float(m.group("mspt"))
                except (TypeError, ValueError):
                    pass
                break
    return sig
