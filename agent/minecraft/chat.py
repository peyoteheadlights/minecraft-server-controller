"""In-game chat: what the console printed, and messages sent as "Server".

Chat is read from the server's own console output (the same lines the
Console page shows), so every message here was really printed by Minecraft.
Nothing is reconstructed from what this app sent: a message this app sends
appears in the chat view only once the console prints it back.

Sending goes through the normal ``say`` command and the same validation
every console command passes (agent/minecraft/commands.py), so the chat box
can no more reach the operating system than the console can.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .console import ConsoleLine

# What a player said: "<Alex> hello". Minecraft 1.19+ prefixes unsigned
# messages with "[Not Secure] ". Floodgate's "." prefix marks a Bedrock
# player and is kept, because that is the name the server printed.
PLAYER_CHAT_RE = re.compile(
    r"^(?:\[Not Secure\]\s*)?<(?P<name>\.?[A-Za-z0-9_]{1,16})>\s?(?P<text>.*)$"
)
# What the server said, which is what `say` prints: "[Server] back in a bit".
SERVER_CHAT_RE = re.compile(r"^\[Server\]\s?(?P<text>.*)$")
# An action, from /me: "* Alex waves".
ACTION_RE = re.compile(r"^\*\s(?P<name>\.?[A-Za-z0-9_]{1,16})\s(?P<text>.+)$")

# What may be sent as a chat message. Deliberately narrower than Minecraft
# allows: these are the characters a console command may carry (see
# commands.ALLOWED_CHARS_RE), minus the ones that would end the line.
MESSAGE_RE = re.compile(r"^[A-Za-z0-9 _:,.\-=+*/@~^\[\]()'\"!?#%]{1,220}$")

KEEP = 400


class ChatError(ValueError):
    """The message can't be sent. Written for people."""


def check_message(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ChatError("Type a message first.")
    if len(text) > 220:
        raise ChatError("Keep a message to 220 characters or fewer.")
    if not MESSAGE_RE.match(text):
        raise ChatError("Use letters, numbers and basic punctuation only.")
    return text


@dataclass
class ChatMessage:
    seq: int
    ts: float
    kind: str  # player | server | action
    name: str | None  # who said it, as the console printed it
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "name": self.name,
            "text": self.text,
        }


def parse_chat(line: ConsoleLine) -> tuple[str, str | None, str] | None:
    """(kind, name, text) for a console line that is chat, else None.

    Only the server's own output counts. A command this app echoed into the
    console view is not chat, even when it begins with "say".
    """
    if line.source != "stdout":
        return None
    text = (line.message or "").strip()
    if not text:
        return None
    if m := PLAYER_CHAT_RE.match(text):
        return "player", m.group("name"), m.group("text")
    if m := SERVER_CHAT_RE.match(text):
        return "server", None, m.group("text")
    if m := ACTION_RE.match(text):
        return "action", m.group("name"), m.group("text")
    return None


async def say(server, text: str) -> str:
    """Send one message to everyone in the game, as "Server".

    The text is checked here, turned into a normal ``say`` command, and
    validated like any console command before it reaches the server.
    """
    from .commands import validate

    message = check_message(text)
    validated = validate(f"say {message}", confirm=True)
    if not server.running or server.state.value != "ONLINE":
        raise ChatError("The server has to be running to send a message.")
    await server.send_command(validated.raw)
    return message


class ChatLog:
    """One server's recent chat, as read from its console.

    Bounded like the console buffer: a long session can print thousands of
    lines, and a phone is only ever served the last slice of them.
    """

    def __init__(self, maxlen: int = KEEP):
        self._messages: deque[ChatMessage] = deque(maxlen=maxlen)
        self._seq = 0

    def add(self, line: ConsoleLine) -> ChatMessage | None:
        parsed = parse_chat(line)
        if parsed is None:
            return None
        kind, name, text = parsed
        self._seq += 1
        message = ChatMessage(
            seq=self._seq, ts=line.ts or time.time(), kind=kind, name=name, text=text
        )
        self._messages.append(message)
        return message

    def tail(self, count: int = 100) -> list[ChatMessage]:
        count = max(1, min(int(count), self._messages.maxlen or KEEP))
        return list(self._messages)[-count:]

    def since(self, seq: int, limit: int = 200) -> list[ChatMessage]:
        return [m for m in self._messages if m.seq > seq][-limit:]

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
