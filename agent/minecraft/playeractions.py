"""The Players page's buttons: whitelist, operator, kick, ban and unban.

Each button sends the normal Minecraft command, built here from a fixed
template and a player name that has passed NAME_RE, and then through the
same validation every console command goes through
(agent/minecraft/commands.py). Nothing else reaches the console.

What happened is only known from the server's own answer (house rule 1):
an action is "sent" when the command was written to the console, and
becomes "done" only when the console prints Minecraft's confirmation
("Added Alex to the whitelist"). An answer meaning nothing changed ("Player
is already whitelisted") or that it failed ("No player was found") is
reported as that. With no answer at all it stays "sent": the app doesn't
claim it worked.

The lists of who is on the whitelist, who is an operator and who is banned
come from the files Minecraft itself keeps (whitelist.json, ops.json,
banned-players.json), never from what this app sent.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..events import Event
from .commands import validate

if TYPE_CHECKING:
    from ..events import ServerBus
    from .console import ConsoleLine
    from .process import MinecraftServer

log = logging.getLogger("msc.playeractions")

# A Java account name, with Floodgate's "." prefix allowed for a Bedrock
# player (shown and used exactly as the server printed it).
NAME_RE = re.compile(r"^\.?[A-Za-z0-9_]{1,16}$")
# A kick or ban reason: one short line in the characters console commands allow.
REASON_RE = re.compile(r"^[A-Za-z0-9 _,.'!?()\-]{0,100}$")
# How long an action waits for the console's answer before it is left as
# "sent" (the dashboard then says the server didn't confirm it).
CONFIRM_SECONDS = 20.0
KEEP = 50

SENT = "sent"
DONE = "done"
UNCHANGED = "unchanged"
FAILED = "failed"
NO_ANSWER = "no_answer"


class PlayerActionError(ValueError):
    """The action can't be sent. Written for people."""


@dataclass(frozen=True)
class Action:
    command: str  # with {name} and, for kick and ban, an optional {reason}
    done: tuple[str, ...]  # Minecraft's confirmations, with {name}
    unchanged: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    confirm: bool = False  # the dashboard asks first
    takes_reason: bool = False


# The exact English lines vanilla Minecraft (and Paper, Forge and the rest,
# which use the same commands) prints for each.
ACTIONS: dict[str, Action] = {
    "whitelist_add": Action(
        "whitelist add {name}",
        done=(r"Added {name} to the whitelist",),
        unchanged=(r"Player is already whitelisted",),
        failed=(r"That player does not exist",),
    ),
    "whitelist_remove": Action(
        "whitelist remove {name}",
        done=(r"Removed {name} from the whitelist",),
        unchanged=(r"Player is not whitelisted",),
        failed=(r"That player does not exist",),
    ),
    "op": Action(
        "op {name}",
        done=(r"Made {name} a server operator",),
        unchanged=(r"Nothing changed\. The player already is an operator",),
        failed=(r"That player does not exist",),
    ),
    "deop": Action(
        "deop {name}",
        done=(r"Made {name} no longer a server operator",),
        unchanged=(r"Nothing changed\. The player is not an operator",),
        failed=(r"That player does not exist",),
    ),
    "kick": Action(
        "kick {name}",
        done=(r"Kicked {name}\b",),
        failed=(r"No player was found",),
        confirm=True,
        takes_reason=True,
    ),
    "ban": Action(
        "ban {name}",
        done=(r"Banned {name}\b",),
        unchanged=(r"Nothing changed\. The player is already banned",),
        failed=(r"That player does not exist",),
        confirm=True,
        takes_reason=True,
    ),
    "pardon": Action(
        "pardon {name}",
        done=(r"Unbanned {name}\b",),
        unchanged=(r"Nothing changed\. The player isn't banned",),
        failed=(r"That player does not exist",),
    ),
}

# What each action is called in events and alerts.
DONE_MESSAGES = {
    "whitelist_add": "{name} was added to the whitelist",
    "whitelist_remove": "{name} was taken off the whitelist",
    "op": "{name} is now an operator",
    "deop": "{name} is no longer an operator",
    "kick": "{name} was kicked",
    "ban": "{name} was banned",
    "pardon": "{name} was unbanned",
}


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise PlayerActionError(
            "That isn't a Minecraft name. Names are up to 16 letters, numbers or _."
        )
    return name


def build_command(kind: str, name: str, reason: str = "") -> str:
    action = ACTIONS.get(kind)
    if action is None:
        raise PlayerActionError("That isn't something the Players page can do.")
    name = check_name(name)
    command = action.command.format(name=name)
    reason = (reason or "").strip()
    if reason:
        if not action.takes_reason:
            raise PlayerActionError("Only a kick or a ban takes a reason.")
        if not REASON_RE.match(reason):
            raise PlayerActionError(
                "Keep the reason to one short line of letters, numbers and basic punctuation."
            )
        command = f"{command} {reason}"
    return command


@dataclass
class PendingAction:
    id: str
    kind: str
    name: str
    command: str
    sent_at: float
    state: str = SENT
    message: str | None = None  # the console line that answered
    answered_at: float | None = None
    patterns: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("patterns", None)
        return data


class PlayerActions:
    """Sends the player commands for one server and watches its console
    for the answers."""

    def __init__(self, server: MinecraftServer, bus: ServerBus):
        self.server = server
        self.bus = bus
        self._actions: dict[str, PendingAction] = {}

    async def send(self, kind: str, name: str, reason: str = "", confirm: bool = False):
        action = ACTIONS.get(kind)
        if action is None:
            raise PlayerActionError("That isn't something the Players page can do.")
        if action.confirm and not confirm:
            raise PlayerActionError("This needs to be confirmed first.")
        command = build_command(kind, name, reason)
        # The same validation every console command passes. The buttons are
        # the person's explicit choice, so the "are you sure" part is the
        # dashboard's dialog (for kick and ban) rather than a second prompt.
        validated = validate(command, confirm=True)
        if not self.server.running or self.server.state.value != "ONLINE":
            raise PlayerActionError(
                "The server has to be running for this. Start it, then try again."
            )
        name = check_name(name)
        escaped = re.escape(name)
        pending = PendingAction(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            name=name,
            command=validated.raw,
            sent_at=time.time(),
            patterns={
                state: [p.replace("{name}", escaped) for p in getattr(action, state)]
                for state in ("done", "unchanged", "failed")
            },
        )
        self._remember(pending)
        await self.server.send_command(validated.raw)
        return pending

    def _remember(self, pending: PendingAction) -> None:
        self._actions[pending.id] = pending
        while len(self._actions) > KEEP:
            self._actions.pop(next(iter(self._actions)))

    def get(self, action_id: str) -> PendingAction | None:
        pending = self._actions.get(action_id)
        if pending:
            self._expire(pending)
        return pending

    def recent(self) -> list[PendingAction]:
        for pending in self._actions.values():
            self._expire(pending)
        return list(reversed(self._actions.values()))

    def _expire(self, pending: PendingAction) -> None:
        if pending.state == SENT and time.time() - pending.sent_at > CONFIRM_SECONDS:
            pending.state = NO_ANSWER

    async def handle(self, sig, line: ConsoleLine) -> None:
        """Console hook: match the server's answer to the oldest action
        still waiting for one.

        Only a line that *starts* with Minecraft's answer counts. A chat
        message ("<Steve> Added Bob to the whitelist") or another operator's
        echoed command ("[Steve: Made Bob a server operator]") contains the
        same words but is not the server answering this button. Names are
        matched without regard to case: Minecraft prints the account's own
        spelling ("Alex"), which may differ from what was typed ("alex")."""
        if line.source != "stdout":
            return
        text = (line.message or line.raw).strip()
        for pending in list(self._actions.values()):
            self._expire(pending)
            if pending.state != SENT:
                continue
            for state, patterns in pending.patterns.items():
                if any(re.match(p, text, re.IGNORECASE) for p in patterns):
                    await self._answer(pending, state, text)
                    return

    async def _answer(self, pending: PendingAction, state: str, text: str) -> None:
        pending.state = {"done": DONE, "unchanged": UNCHANGED, "failed": FAILED}[state]
        pending.message = text.strip()[:300]
        pending.answered_at = time.time()
        if pending.state != DONE:
            return
        await self.bus.publish(
            Event(
                type="player_action",
                level="info",
                message=DONE_MESSAGES[pending.kind].format(name=pending.name),
                data={
                    "action": pending.kind,
                    "username": pending.name,
                    "confirmed_by": "server console",
                },
            )
        )


# ----------------------------------------------------------------------
# what Minecraft's own files say
# ----------------------------------------------------------------------
LIST_FILES = {
    "whitelist": "whitelist.json",
    "ops": "ops.json",
    "banned": "banned-players.json",
}
MAX_LIST_BYTES = 2 * 1024 * 1024


def read_list(directory: Path, which: str) -> dict[str, Any]:
    """One of Minecraft's player lists. ``players`` is None, with the
    reason, when the file isn't there yet or can't be read."""
    path = directory / LIST_FILES[which]
    if not path.is_file():
        return {
            "players": None,
            "file": path.name,
            "reason": f"{path.name} isn't there yet. Minecraft writes it the first time it starts.",
        }
    try:
        if path.stat().st_size > MAX_LIST_BYTES:
            raise ValueError("the file is far bigger than a player list")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("it doesn't hold a list")
    except (OSError, ValueError) as exc:
        return {
            "players": None,
            "file": path.name,
            "reason": f"{path.name} couldn't be read ({exc}).",
        }
    players = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        entry: dict[str, Any] = {"name": item["name"], "uuid": item.get("uuid")}
        if which == "ops":
            entry["level"] = item.get("level")
        if which == "banned":
            entry.update(
                created=item.get("created"),
                source=item.get("source"),
                expires=item.get("expires"),
                reason=item.get("reason"),
            )
        players.append(entry)
    return {"players": players, "file": path.name, "reason": None}


def lists(directory: Path) -> dict[str, Any]:
    return {which: read_list(directory, which) for which in LIST_FILES}
