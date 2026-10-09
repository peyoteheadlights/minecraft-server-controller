"""A small, read-only reader for Minecraft's NBT format, enough to read a
world's level.dat: its name, the Minecraft version that last saved it, and
when it was last played.

Java's level.dat is a gzip-compressed, big-endian NBT compound. Bedrock's
is an 8-byte header (storage version and length, little-endian) followed by
an uncompressed little-endian NBT compound; ``bedrock_level_info`` reads it. Only the values a person is
shown are kept; everything else is read past. The input comes from files
people upload, so sizes are capped, the nesting depth is limited, and any
malformed input raises NbtError rather than being guessed at.
"""

from __future__ import annotations

import gzip
import io
import struct
from typing import Any

MAX_COMPRESSED = 16 * 1024 * 1024
MAX_UNCOMPRESSED = 64 * 1024 * 1024
MAX_DEPTH = 64

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND = range(11)
INT_ARRAY, LONG_ARRAY = 11, 12


class NbtError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes, order: str = ">"):
        self.data = data
        self.pos = 0
        self.order = order  # ">" for Java, "<" for Bedrock

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise NbtError("level.dat ends too early")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt: str) -> Any:
        fmt = self.order + fmt.lstrip("<>")
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        length = self.unpack(">H")
        return self.take(length).decode("utf-8", errors="replace")

    def payload(self, tag: int, depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise NbtError("level.dat is nested too deeply")
        if tag == BYTE:
            return self.unpack(">b")
        if tag == SHORT:
            return self.unpack(">h")
        if tag == INT:
            return self.unpack(">i")
        if tag == LONG:
            return self.unpack(">q")
        if tag == FLOAT:
            return self.unpack(">f")
        if tag == DOUBLE:
            return self.unpack(">d")
        if tag == BYTE_ARRAY:
            self.take(self.unpack(">i"))
            return None
        if tag == STRING:
            return self.string()
        if tag == LIST:
            inner = self.unpack(">b")
            count = self.unpack(">i")
            if count < 0:
                raise NbtError("level.dat has a list with a negative length")
            if inner == COMPOUND or inner == LIST:
                return [self.payload(inner, depth + 1) for _ in range(count)]
            if inner in (BYTE, SHORT, INT, LONG) and count <= 16:
                # Short number lists are kept: Bedrock's version is one.
                return [self.payload(inner, depth + 1) for _ in range(count)]
            for _ in range(count):
                self.payload(inner, depth + 1)
            return None
        if tag == COMPOUND:
            found: dict[str, Any] = {}
            while True:
                kind = self.unpack(">b")
                if kind == END:
                    return found
                name = self.string()
                found[name] = self.payload(kind, depth + 1)
        if tag == INT_ARRAY:
            self.take(4 * self.unpack(">i"))
            return None
        if tag == LONG_ARRAY:
            self.take(8 * self.unpack(">i"))
            return None
        raise NbtError(f"level.dat has an unknown tag type {tag}")


def read(data: bytes) -> dict[str, Any]:
    """The root compound of an NBT file, gzip-compressed or not."""
    if len(data) > MAX_COMPRESSED:
        raise NbtError("level.dat is far too big to be one")
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
                data = fh.read(MAX_UNCOMPRESSED + 1)
        except (OSError, EOFError) as exc:
            raise NbtError(f"level.dat couldn't be unpacked: {exc}") from exc
        if len(data) > MAX_UNCOMPRESSED:
            raise NbtError("level.dat unpacks to far too much data")
    reader = _Reader(data)
    try:
        if reader.unpack(">b") != COMPOUND:
            raise NbtError("level.dat doesn't start the way a level.dat does")
        reader.string()
        root = reader.payload(COMPOUND, 0)
    except struct.error as exc:  # pragma: no cover - take() checks lengths first
        raise NbtError(str(exc)) from exc
    return root


def level_info(data: bytes) -> dict[str, Any]:
    """The facts a person is shown about a world, read from its level.dat:
    {"name", "version", "last_played"}. A value the file doesn't hold is
    None, never filled in."""
    root = read(data)
    level = root.get("Data")
    if not isinstance(level, dict):
        raise NbtError("level.dat has no world data in it")
    name = level.get("LevelName")
    version = level.get("Version")
    version_name = version.get("Name") if isinstance(version, dict) else None
    last = level.get("LastPlayed")
    return {
        "name": str(name)[:100] if isinstance(name, str) and name.strip() else None,
        "version": str(version_name)[:40] if isinstance(version_name, str) else None,
        # LastPlayed is milliseconds since 1970.
        "last_played": last / 1000 if isinstance(last, int) and last > 0 else None,
    }


BEDROCK_HEADER = 8


def read_bedrock(data: bytes) -> dict[str, Any]:
    """The root compound of a Bedrock level.dat."""
    if len(data) > MAX_COMPRESSED:
        raise NbtError("level.dat is far too big to be one")
    if len(data) < BEDROCK_HEADER + 3:
        raise NbtError("level.dat ends too early")
    length = struct.unpack("<i", data[4:8])[0]
    body = data[BEDROCK_HEADER:]
    if length <= 0 or length > len(body):
        raise NbtError("level.dat's header doesn't match its size")
    reader = _Reader(body[:length], "<")
    if reader.unpack("b") != COMPOUND:
        raise NbtError("level.dat doesn't start the way a Bedrock level.dat does")
    reader.string()
    return reader.payload(COMPOUND, 0)


def is_bedrock_level(data: bytes) -> bool:
    """True when this looks like Bedrock's level.dat (not gzip, and the
    header's length matches the rest)."""
    if len(data) < BEDROCK_HEADER + 3 or data[:2] == b"\x1f\x8b":
        return False
    length = struct.unpack("<i", data[4:8])[0]
    return length == len(data) - BEDROCK_HEADER and data[BEDROCK_HEADER] == COMPOUND


def bedrock_level_info(data: bytes) -> dict[str, Any]:
    """{"name", "version", "last_played"} from a Bedrock level.dat. The
    version is lastOpenedWithVersion (the game version that last saved it)."""
    root = read_bedrock(data)
    name = root.get("LevelName")
    opened = root.get("lastOpenedWithVersion")
    version = None
    if isinstance(opened, list) and opened and all(isinstance(n, int) for n in opened):
        parts = list(opened)
        while len(parts) > 3 and parts[-1] == 0:
            parts.pop()
        version = ".".join(str(n) for n in parts)
    last = root.get("LastPlayed")
    return {
        "name": str(name)[:100] if isinstance(name, str) and name.strip() else None,
        "version": version,
        # Bedrock's LastPlayed is seconds since 1970.
        "last_played": float(last) if isinstance(last, int) and last > 0 else None,
    }


def write_for_tests(level: dict[str, Any]) -> bytes:
    """A gzip-compressed level.dat holding ``level`` as its Data compound.
    Only strings, ints (as TAG_Long when large), and nested dicts. Used by
    the tests to make real-looking worlds."""

    def encode(value: Any) -> tuple[int, bytes]:
        if isinstance(value, dict):
            body = b"".join(named(k, v) for k, v in value.items()) + bytes([END])
            return COMPOUND, body
        if isinstance(value, str):
            raw = value.encode("utf-8")
            return STRING, struct.pack(">H", len(raw)) + raw
        if isinstance(value, int):
            if -(2**31) <= value < 2**31:
                return INT, struct.pack(">i", value)
            return LONG, struct.pack(">q", value)
        raise TypeError(type(value))

    def named(key: str, value: Any) -> bytes:
        tag, body = encode(value)
        raw = key.encode("utf-8")
        return bytes([tag]) + struct.pack(">H", len(raw)) + raw + body

    root = named("", {"Data": level})
    return gzip.compress(root)


def bedrock_level_for_tests(name: str, version: list[int], last_played: int = 0) -> bytes:
    """A Bedrock level.dat with a name, lastOpenedWithVersion and
    LastPlayed, laid out the way Bedrock writes it. Used by the tests."""

    def text(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<H", len(raw)) + raw

    body = bytes([STRING]) + text("LevelName") + text(name)
    body += bytes([LIST]) + text("lastOpenedWithVersion") + bytes([INT])
    body += struct.pack("<i", len(version)) + b"".join(struct.pack("<i", n) for n in version)
    body += bytes([LONG]) + text("LastPlayed") + struct.pack("<q", last_played)
    root = bytes([COMPOUND]) + text("") + body + bytes([END])
    return struct.pack("<i", 10) + struct.pack("<i", len(root)) + root
