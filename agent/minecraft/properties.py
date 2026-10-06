"""Reading and editing a server's server.properties.

The Game settings page edits a handful of well-known keys (FIELDS) with
normal controls. Everything else in the file is left exactly as it was:

  * comments, blank lines, the order of keys and every key this module
    doesn't know are kept byte for byte
  * only a known key's own line is rewritten, and only when its value
    changes
  * a value is checked against its field before anything is written; one
    bad value means nothing is written at all
  * the file is written to a temporary name and renamed into place, so a
    crash part way never leaves half a file

The format is Java's .properties format, which Minecraft reads as
ISO-8859-1: backslash escapes (``\\:``, ``\\uXXXX``) are decoded when read
and non-ASCII characters are written as ``\\uXXXX``, the way Minecraft
writes them itself.

The values are what the file says. A key the file doesn't set is reported
as not set, together with the value Minecraft itself uses then (its own
documented default, not a guess about this server).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FILENAME = "server.properties"
MAX_FILE_BYTES = 256 * 1024
MAX_TEXT = 150

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,79}$")


class PropertiesError(ValueError):
    """A value or the file itself can't be used. Written for people."""


# ----------------------------------------------------------------------
# the format
# ----------------------------------------------------------------------
_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}


def unescape(text: str) -> str:
    """Decode a .properties value: ``\\uXXXX``, ``\\t`` and friends, and a
    backslash before any other character meaning that character."""
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char != "\\" or i + 1 >= len(text):
            out.append(char)
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "u" and re.fullmatch(r"[0-9A-Fa-f]{4}", text[i + 2 : i + 6] or ""):
            out.append(chr(int(text[i + 2 : i + 6], 16)))
            i += 6
            continue
        out.append(_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def escape(value: str) -> str:
    """Encode a value the way Minecraft writes it."""
    out: list[str] = []
    for index, char in enumerate(value):
        if char == "\\":
            out.append("\\\\")
        elif char == ":":
            out.append("\\:")
        elif char == "=":
            out.append("\\=")
        elif char == " " and index == 0:
            out.append("\\ ")
        elif char in ("#", "!") and index == 0:
            out.append("\\" + char)
        elif ord(char) < 0x20 or ord(char) > 0x7E:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return "".join(out)


@dataclass
class Entry:
    """One logical line of the file: a key and value, or anything else
    (a comment, a blank line), kept as the physical lines it came from."""

    raw: list[str]
    key: str | None = None
    value: str | None = None


def _split(logical: str) -> tuple[str, str] | None:
    text = logical.lstrip(" \t\f")
    if not text or text[0] in "#!":
        return None
    key_chars: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            key_chars.append(text[i : i + 2])
            i += 2
            continue
        if char in "=: \t\f":
            break
        key_chars.append(char)
        i += 1
    rest = text[i:].lstrip(" \t\f")
    if rest[:1] in ("=", ":"):
        rest = rest[1:].lstrip(" \t\f")
    return unescape("".join(key_chars)), unescape(rest)


def _continues(line: str) -> bool:
    """A line ending in an odd number of backslashes carries on."""
    stripped = line.rstrip("\r\n")
    count = len(stripped) - len(stripped.rstrip("\\"))
    return count % 2 == 1


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        raw = [lines[i]]
        logical = lines[i].rstrip("\r\n")
        is_comment = logical.lstrip(" \t\f")[:1] in ("#", "!")
        while not is_comment and _continues(raw[-1]) and i + 1 < len(lines):
            i += 1
            raw.append(lines[i])
            logical = logical[:-1] + lines[i].rstrip("\r\n").lstrip(" \t\f")
        i += 1
        split = _split(logical)
        if split is None:
            entries.append(Entry(raw=raw))
        else:
            entries.append(Entry(raw=raw, key=split[0], value=split[1]))
    return entries


class PropertiesFile:
    """A server.properties file, kept as it was read."""

    def __init__(self, text: str = "", newline: str = "\n"):
        self.entries = parse(text)
        self.newline = newline

    @classmethod
    def read(cls, path: Path) -> PropertiesFile:
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise PropertiesError(
                f"{path.name} is bigger than {MAX_FILE_BYTES // 1024} KB, which a real "
                "server.properties never is, so it wasn't opened."
            )
        # surrogateescape keeps any byte that isn't UTF-8 exactly as it was
        text = data.decode("utf-8", errors="surrogateescape")
        return cls(text, "\r\n" if "\r\n" in text else "\n")

    def values(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for entry in self.entries:
            if entry.key is not None:
                found[entry.key] = entry.value or ""
        return found

    def get(self, key: str) -> str | None:
        return self.values().get(key)

    def set(self, key: str, value: str) -> bool:
        """Set one key. Returns False when it already had this value, in
        which case nothing in the file changes."""
        if self.get(key) == value:
            return False
        line = f"{key}={escape(value)}{self.newline}"
        matches = [e for e in self.entries if e.key == key]
        if matches:
            # The last one is what Minecraft uses; the earlier ones are left.
            matches[-1].raw = [line]
            matches[-1].value = value
        else:
            if self.entries and not self.entries[-1].raw[-1].endswith(("\n", "\r")):
                self.entries[-1].raw[-1] += self.newline
            self.entries.append(Entry(raw=[line], key=key, value=value))
        return True

    def text(self) -> str:
        return "".join("".join(entry.raw) for entry in self.entries)

    def write(self, path: Path) -> None:
        data = self.text().encode("utf-8", errors="surrogateescape")
        temp = path.with_name(f".{path.name}.writing")
        temp.write_bytes(data)
        os.replace(temp, path)


# ----------------------------------------------------------------------
# the known keys
# ----------------------------------------------------------------------
GAMEMODES = ("survival", "creative", "adventure", "spectator")
DIFFICULTIES = ("peaceful", "easy", "normal", "hard")
# Older servers wrote numbers for these; Minecraft reads both.
LEGACY_NUMBERS = {"gamemode": GAMEMODES, "difficulty": DIFFICULTIES}


@dataclass(frozen=True)
class Field:
    key: str
    kind: str  # "choice", "bool", "int", "text", "port", "seed"
    # What Minecraft uses when the file doesn't set the key.
    minecraft_default: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = MAX_TEXT
    extra: dict[str, Any] = field(default_factory=dict)


FIELDS: tuple[Field, ...] = (
    Field("difficulty", "choice", "easy", choices=DIFFICULTIES),
    Field("gamemode", "choice", "survival", choices=GAMEMODES),
    Field("max-players", "int", "20", minimum=1, maximum=10000),
    Field("level-seed", "seed", "", max_length=100),
    Field("white-list", "bool", "false"),
    Field("pvp", "bool", "true"),
    Field("view-distance", "int", "10", minimum=3, maximum=32),
    Field("motd", "text", "A Minecraft Server"),
    Field("server-port", "port", "25565", minimum=1024, maximum=65535),
)
FIELDS_BY_KEY = {f.key: f for f in FIELDS}


def read_value(spec: Field, raw: str | None) -> tuple[Any, str | None]:
    """The typed value of a key as the file has it, and a problem when the
    file holds something Minecraft wouldn't accept for it."""
    if raw is None:
        return None, None
    text = raw.strip()
    if spec.kind == "choice":
        lowered = text.lower()
        if lowered in spec.choices:
            return lowered, None
        legacy = LEGACY_NUMBERS.get(spec.key)
        if legacy and text.isdigit() and int(text) < len(legacy):
            return legacy[int(text)], None
        return None, f"'{raw}' isn't one of: {', '.join(spec.choices)}"
    if spec.kind == "bool":
        if text.lower() in ("true", "false"):
            return text.lower() == "true", None
        return None, f"'{raw}' isn't true or false"
    if spec.kind in ("int", "port"):
        try:
            return int(text), None
        except ValueError:
            return None, f"'{raw}' isn't a whole number"
    return raw, None


def check_value(spec: Field, value: Any) -> str:
    """Turn a value from the form into the text written to the file, or
    raise PropertiesError saying what is wrong with it."""
    if spec.kind == "choice":
        text = str(value or "").strip().lower()
        if text not in spec.choices:
            raise PropertiesError(f"Pick one of: {', '.join(spec.choices)}.")
        return text
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise PropertiesError("This has to be on or off.")
        return "true" if value else "false"
    if spec.kind in ("int", "port"):
        if isinstance(value, bool):
            raise PropertiesError("This has to be a whole number.")
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise PropertiesError("This has to be a whole number.") from None
        if str(value).strip() not in (str(number), f"+{number}"):
            raise PropertiesError("This has to be a whole number.")
        if spec.minimum is not None and number < spec.minimum:
            raise PropertiesError(f"The smallest it can be is {spec.minimum}.")
        if spec.maximum is not None and number > spec.maximum:
            raise PropertiesError(f"The biggest it can be is {spec.maximum}.")
        return str(number)
    text = "" if value is None else str(value)
    if "\n" in text or "\r" in text or "\0" in text:
        raise PropertiesError("This has to be one line.")
    if len(text) > spec.max_length:
        raise PropertiesError(f"This can be at most {spec.max_length} characters.")
    if spec.kind == "seed":
        text = text.strip()
    return text


def world_folder(directory: Path, values: dict[str, str]) -> Path:
    """The folder the world lives in, from level-name (Minecraft's own
    default is "world")."""
    name = (values.get("level-name") or "world").strip() or "world"
    return directory / name


def world_folders(directory: Path) -> set[str]:
    """The folders that make up the world: level-name and, for Paper,
    Purpur and Spigot's split dimensions, its _nether and _the_end."""
    path = directory / FILENAME
    values = PropertiesFile.read(path).values() if path.is_file() else {}
    name = world_folder(directory, values).name
    return {name, f"{name}_nether", f"{name}_the_end"}


def world_exists(directory: Path, values: dict[str, str]) -> bool:
    """A world exists once Minecraft has written its level.dat."""
    return (world_folder(directory, values) / "level.dat").is_file()


def check_raw_text(text: str) -> PropertiesFile:
    """Check the whole file as typed in Technical mode. Every line must be
    a comment, blank, or key=value, and every known key must hold a value
    its field accepts. Returns the parsed file."""
    if "\0" in text:
        raise PropertiesError("The text has a character in it a settings file can't hold.")
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise PropertiesError(f"That is more than {MAX_FILE_BYTES // 1024} KB of settings.")
    parsed = PropertiesFile(text)
    problems = []
    for number, entry in enumerate(parsed.entries, start=1):
        if entry.key is None:
            continue
        if not KEY_RE.match(entry.key):
            problems.append(f"Line {number}: '{entry.key}' doesn't look like a setting name.")
            continue
        spec = FIELDS_BY_KEY.get(entry.key)
        if spec is None:
            continue
        typed, problem = read_value(spec, entry.value)
        if problem:
            problems.append(f"{entry.key}: {problem}.")
            continue
        try:
            check_value(spec, typed)
        except PropertiesError as exc:
            problems.append(f"{entry.key}: {exc}")
    if problems:
        raise PropertiesError(" ".join(problems[:5]))
    return parsed


PortCheck = Callable[[int], str | None]


def form_view(directory: Path) -> dict[str, Any]:
    """What the Game settings page shows: each known key's value as the
    file has it, whether the file exists, and the whole text."""
    path = directory / FILENAME
    exists = path.is_file()
    parsed = PropertiesFile.read(path) if exists else PropertiesFile()
    values = parsed.values()
    has_world = world_exists(directory, values)
    fields = []
    for spec in FIELDS:
        raw = values.get(spec.key)
        typed, problem = read_value(spec, raw)
        read_only = None
        if spec.key == "level-seed" and has_world:
            read_only = "world_exists"
        fields.append(
            {
                "key": spec.key,
                "kind": spec.kind,
                "value": typed,
                "raw": raw,
                "set": raw is not None,
                "problem": problem,
                "minecraft_default": spec.minecraft_default,
                "choices": list(spec.choices),
                "min": spec.minimum,
                "max": spec.maximum,
                "max_length": spec.max_length,
                "read_only": read_only,
            }
        )
    return {
        "file": str(path),
        "exists": exists,
        "modified_at": path.stat().st_mtime if exists else None,
        "world_exists": has_world,
        "world_folder": world_folder(directory, values).name,
        "fields": fields,
        "text": parsed.text(),
    }


def apply_form(
    directory: Path,
    updates: dict[str, Any],
    port_problem: PortCheck | None = None,
) -> tuple[PropertiesFile, dict[str, str]]:
    """Check every update and return the edited file (not yet written) and
    the keys that change. Raises PropertiesError naming each bad value."""
    path = directory / FILENAME
    parsed = PropertiesFile.read(path) if path.is_file() else PropertiesFile()
    values = parsed.values()
    problems: dict[str, str] = {}
    texts: dict[str, str] = {}
    for key, value in updates.items():
        spec = FIELDS_BY_KEY.get(key)
        if spec is None:
            problems[key] = "This setting can't be changed here."
            continue
        try:
            text = check_value(spec, value)
        except PropertiesError as exc:
            problems[key] = str(exc)
            continue
        if key == "level-seed" and text != (values.get(key) or "").strip():
            if world_exists(directory, values):
                problems[key] = (
                    "The world already exists, so its seed can't change. A new seed only "
                    "applies to a new world."
                )
                continue
        if spec.kind == "port" and port_problem and text != values.get(key):
            found = port_problem(int(text))
            if found:
                problems[key] = found
                continue
        texts[key] = text
    if problems:
        raise FormError(problems)
    changed = {key: text for key, text in texts.items() if parsed.set(key, text)}
    return parsed, changed


class FormError(PropertiesError):
    """One or more values were refused; ``problems`` maps key to reason."""

    def __init__(self, problems: dict[str, str]):
        self.problems = problems
        super().__init__(" ".join(f"{k}: {v}" for k, v in problems.items()))
