"""Validation for commands sent to the Minecraft console.

This module exists so that the remote console can never become a Windows
shell. Everything that reaches MinecraftServer.send_command() has passed
through validate().

Rules:
  * exactly one line, no newlines, no NUL
  * bounded length
  * the first token must look like a Minecraft command name
  * characters are restricted to a printable set that Minecraft commands use
  * shell metacharacters (` ; & | < > $ and newlines) are rejected outright,
    even though nothing here is ever handed to a shell - defence in depth.
    None of them appear in Minecraft command syntax.
  * a set of high-impact commands requires explicit confirmation
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LENGTH = 512

COMMAND_NAME_RE = re.compile(r"^/?[a-z][a-z0-9_:-]{0,31}$")
# Minecraft command text: letters, digits, and the punctuation used by
# selectors, NBT, coordinates, JSON text components and quoted strings.
# Pipes, ampersands and redirection have no role in Minecraft command syntax,
# so they are excluded outright rather than only in their doubled forms.
ALLOWED_CHARS_RE = re.compile(r"^[A-Za-z0-9 _:,.\-=+*/@~^\[\]{}()'\"!?#%\\]*$")
SHELL_META_RE = re.compile(r"[`;&|<>$\r\n\0]")

DANGEROUS_COMMANDS = {
    "stop": "This shuts the Minecraft server down.",
    "ban": "This bans a player from the server.",
    "ban-ip": "This bans an IP address from the server.",
    "pardon": "This removes a ban.",
    "pardon-ip": "This removes an IP ban.",
    "kick": "This disconnects a player.",
    "op": "This grants operator permissions.",
    "deop": "This removes operator permissions.",
    "whitelist": "This changes who may join the server.",
    "kill": "This kills entities, and with a broad selector it can kill every player.",
    "difficulty": "This changes world difficulty for everyone.",
    "gamerule": "This changes a world rule for everyone.",
    "setworldspawn": "This moves the world spawn point.",
    "save-off": "This disables world saving, which risks data loss if the server dies.",
    "forceload": "This permanently keeps chunks loaded and can hurt performance.",
    "reload": "Reloading datapacks on a modded server can destabilise it.",
    "datapack": "This enables or disables datapacks.",
}

# Commands that the agent refuses entirely: they belong to the agent's own
# control surface, not to an ad-hoc console string.
BLOCKED_COMMANDS: dict[str, str] = {}


class CommandError(ValueError):
    """Raised when a command is not a valid Minecraft console command."""


@dataclass
class ValidatedCommand:
    raw: str
    name: str
    args: str
    dangerous: bool
    danger_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "command": self.raw,
            "name": self.name,
            "dangerous": self.dangerous,
            "danger_reason": self.danger_reason,
        }


def validate(command: str, confirm: bool = False) -> ValidatedCommand:
    if command is None:
        raise CommandError("No command supplied")
    text = command.strip()
    if not text:
        raise CommandError("No command supplied")
    if len(text) > MAX_LENGTH:
        raise CommandError(f"Command is longer than {MAX_LENGTH} characters")
    if "\n" in command or "\r" in command or "\0" in command:
        raise CommandError("A command must be a single line")
    if SHELL_META_RE.search(text):
        raise CommandError("Command contains characters that are not allowed")
    if not ALLOWED_CHARS_RE.match(text):
        raise CommandError("Command contains characters that are not allowed")

    name_token = text.split(" ", 1)[0]
    if not COMMAND_NAME_RE.match(name_token):
        raise CommandError(
            "The first word must be a Minecraft command name, for example 'say' or 'whitelist'"
        )
    name = name_token.lstrip("/").lower()
    args = text.split(" ", 1)[1] if " " in text else ""

    if name in BLOCKED_COMMANDS:
        raise CommandError(BLOCKED_COMMANDS[name])

    reason = DANGEROUS_COMMANDS.get(name)
    if reason and not confirm:
        raise CommandError(f"'{name}' needs confirmation. {reason}")

    # send without the leading slash; the server console does not use one
    return ValidatedCommand(
        raw=text.lstrip("/"), name=name, args=args, dangerous=bool(reason), danger_reason=reason
    )


def is_dangerous(command: str) -> bool:
    name = command.strip().split(" ", 1)[0].lstrip("/").lower()
    return name in DANGEROUS_COMMANDS


def describe_danger(command: str) -> str | None:
    name = command.strip().split(" ", 1)[0].lstrip("/").lower()
    return DANGEROUS_COMMANDS.get(name)
