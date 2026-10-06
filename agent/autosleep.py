"""Auto-sleep: stop a server that nobody is playing on.

Off by default, and set per server. While it is on, this watches the player
count the PlayerTracker has actually established and, once the server has
been empty for the set number of minutes, warns in the game and then stops
it the same way a scheduled stop does - a planned stop, never a crash.

House rule 1 decides the hard part: the player count is only a fact once
something established it (a join or leave in the console, a /list reply, or
the process being gone). While it is Unknown this never stops the server,
because "nobody is online" would be a guess.

The server does not come back by itself. Starting it again is the person's
choice, from the dashboard or a schedule, and the dashboard says so.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .events import Event
from .minecraft.chat import ChatError, say
from .minecraft.process import ServerError
from .minecraft.state import ExitReason

if TYPE_CHECKING:
    from .core import ServerContext

log = logging.getLogger("msc.autosleep")

# How often the watcher looks. Fast enough that the warning and the stop
# land close to the minute they were promised, slow enough to cost nothing.
CHECK_SECONDS = 15.0
# How long before the stop the players are warned. A warning only goes out
# when the wait is longer than this, so a one-minute wait is not all warning.
WARN_SECONDS = 60.0


class AutoSleep:
    """One server's auto-sleep watcher."""

    def __init__(self, ctx: ServerContext):
        self.ctx = ctx
        # When the server was last seen empty with a verified count. None
        # means it is not currently known to be empty.
        self.empty_since: float | None = None
        self.warned = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.ctx.config.server.autosleep)

    @property
    def minutes(self) -> float:
        return max(1.0, float(self.ctx.config.server.autosleep_minutes))

    def status(self) -> dict[str, object]:
        """What the dashboard shows: the setting, and what is measured."""
        count = self.ctx.players.online_count()
        remaining: float | None = None
        if self.enabled and self.empty_since is not None:
            remaining = max(0.0, self.minutes * 60 - (time.time() - self.empty_since))
        return {
            "enabled": self.enabled,
            "minutes": self.minutes,
            "players_online": count,
            "players_verified": self.ctx.players.verified,
            "empty_since": self.empty_since,
            "stops_in": remaining,
            "warned": self.warned,
        }

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name=f"autosleep-{self.ctx.server_id}")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_SECONDS)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - never take the agent down
                log.exception("auto-sleep check failed for %s", self.ctx.server_id)

    # ------------------------------------------------------------------
    def _reset(self) -> None:
        self.empty_since = None
        self.warned = False

    async def check(self, now: float | None = None) -> str:
        """One pass. Returns what it did, for the tests and the log:
        "off", "not_online", "unknown", "players", "waiting", "warned" or
        "slept"."""
        now = now if now is not None else time.time()
        server = self.ctx.server
        if not self.enabled:
            self._reset()
            return "off"
        if not server.running or server.state.value != "ONLINE":
            self._reset()
            return "not_online"
        count = self.ctx.players.online_count()
        if count is None:
            # Not a verified zero: never stop on a count nobody established.
            self._reset()
            return "unknown"
        if count > 0:
            self._reset()
            return "players"
        if self.empty_since is None:
            self.empty_since = now
            return "waiting"

        # A change already running on this server owns it; sleeping can wait.
        if server.held_by or self.ctx.core.jobs.risky_job(self.ctx.server_id):
            return "waiting"

        wait = self.minutes * 60
        empty_for = now - self.empty_since
        if empty_for < wait:
            if not self.warned and wait > WARN_SECONDS and empty_for >= wait - WARN_SECONDS:
                await self._warn()
                return "warned"
            return "waiting"
        return await self._sleep(empty_for)

    async def _warn(self) -> None:
        self.warned = True
        minutes = int(round(WARN_SECONDS / 60)) or 1
        try:
            await say(
                self.ctx.server,
                f"Nobody is playing, so this server will stop in {minutes} minute"
                f"{'' if minutes == 1 else 's'}.",
            )
        except (ChatError, ServerError) as exc:
            # The stop still happens; only the courtesy failed.
            log.info("auto-sleep warning could not be sent: %s", exc)

    async def _sleep(self, empty_for: float) -> str:
        name = self.ctx.name
        minutes = int(empty_for // 60)
        server = self.ctx.server
        # Marks this as a stop the app chose, so the dashboard can say why
        # the server is off and that starting it again is up to the person.
        server.stopped_for_sleep = True
        try:
            await server.stop(actor="auto-sleep", reason=ExitReason.SCHEDULED_STOP)
        except ServerError as exc:
            server.stopped_for_sleep = False
            log.info("auto-sleep could not stop %s: %s", name, exc)
            return "waiting"
        finally:
            self._reset()
        self.ctx.db.audit(
            "autosleep_stop", user="auto-sleep", target=name, detail=f"empty for {minutes} min"
        )
        await self.ctx.bus.publish(
            Event(
                type="autosleep_stopped",
                level="info",
                message=f"Stopped {name}: nobody had been playing for {minutes} minutes",
                data={
                    "server_name": name,
                    "empty_minutes": minutes,
                    "setting_minutes": self.minutes,
                    "start_again": "from the dashboard or a schedule",
                },
            )
        )
        return "slept"
