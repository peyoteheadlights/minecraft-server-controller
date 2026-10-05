"""Automatic TPS command detection and polling.

Minecraft has no single way to report its tick rate. Depending on the
version and the installed mods, one of these may work:

    tick query   vanilla, Minecraft 1.20.3 and newer
    tps          Carpet
    spark tps    spark

When the server finishes starting, each candidate is sent once, in that
order, and the console is watched for a reply that actually contains TPS or
MSPT figures. The first that answers is used for polling from then on and
remembered for next time. A candidate that the server rejects ("Unknown or
incomplete command") is dropped immediately; one that stays silent is
dropped after a short timeout. Detection runs once per server start - never
on a timer.

If nothing answers, TPS is reported as unavailable, with the reason. It is
never estimated.

Configuration (monitor.tps_command):
    "auto"       detect automatically (default)
    "" or "off"  disabled
    anything     used as-is (a manual override); verified once per start
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from ..events import Event, EventBus
from ..minecraft.commands import CommandError, validate
from ..minecraft.console import extract_signals

log = logging.getLogger("msc.tps")

CANDIDATES = ("tick query", "tps", "spark tps")
PROBE_TIMEOUT = 5.0
PROBE_INTERVAL = 0.2
SETTING_KEY = "tps_detected"


def _version_tuple(version: str | None) -> tuple[int, ...] | None:
    match = re.match(r"^(\d+(?:\.\d+)*)", str(version or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def candidates_for(
    minecraft_version: str | None,
    remembered: str | None = None,
    candidates: tuple[str, ...] = CANDIDATES,
) -> list[str]:
    """Candidate commands in the order they should be tried.

    ``candidates`` comes from the server type (Paper answers `tps` itself,
    vanilla only `tick query`). `tick query` is skipped on versions known to
    predate it (1.20.3), so an older server is not sent a command it cannot
    understand. When the version is unknown it is tried anyway: a rejected
    command costs one console line.
    """
    version = _version_tuple(minecraft_version)
    ordered = []
    if remembered:
        ordered.append(remembered)
    for command in candidates:
        if command == "tick query" and version is not None and version < (1, 20, 3):
            continue
        if command not in ordered:
            ordered.append(command)
    return ordered


class TpsMonitor:
    def __init__(self, config, bus: EventBus, db, server):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self._task: asyncio.Task | None = None
        self._probe_lock = asyncio.Lock()
        self.reset_status()

    # ------------------------------------------------------------------ state
    def mode(self) -> str:
        value = str(self.config.monitor.tps_command or "").strip()
        if value.lower() in ("", "off", "none", "disabled"):
            return "disabled"
        if value.lower() == "auto":
            return "auto"
        return "manual"

    def configured_command(self) -> str | None:
        return self.config.monitor.tps_command.strip() if self.mode() == "manual" else None

    def reset_status(self) -> None:
        self.status_data: dict[str, Any] = {
            "mode": self.mode(),
            "state": "idle",
            "command": None,
            "detection": None,
            "tried": [],
            "detected_at": None,
            "message": "Waiting for the server to finish starting.",
        }
        self._publish_status()

    def _publish_status(self) -> None:
        self.status_data["mode"] = self.mode()
        self.server.tps_status = dict(self.status_data)

    def status(self) -> dict[str, Any]:
        data = dict(self.status_data)
        data["mode"] = self.mode()
        data["remembered"] = self.db.get_setting(SETTING_KEY)
        data["tps"] = self.server.tps
        data["mspt"] = self.server.mspt
        data["last_reading_at"] = self.server.tps_updated
        data["poll_interval"] = self.config.monitor.tps_poll_interval
        data["server_state"] = self.server.state.value
        return data

    # ------------------------------------------------------------------ lifecycle
    async def handle(self, event: Event) -> None:
        """Event-bus subscriber."""
        if event.type == "server_started":
            self.begin()
        elif event.type in ("server_stopped", "server_crashed"):
            await self.halt()

    def begin(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._run(), name="tps-monitor")

    async def halt(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self.reset_status()

    def start(self) -> None:
        """Called when the agent starts; picks up a server that is already online."""
        if self.server.state.value == "ONLINE":
            self.begin()

    async def stop(self) -> None:
        await self.halt()

    # ------------------------------------------------------------------ probing
    async def probe(self, command: str, timeout: float = PROBE_TIMEOUT) -> dict[str, Any]:
        """Send one command and report whether it produced tick data.

        Results: ok, rejected (the server said unknown command), silent (no
        usable reply in time), error (the command could not be sent).
        """
        async with self._probe_lock:
            start_seq = self.server.console._seq
            try:
                await self.server.send_command(command, internal=True)
            except Exception as exc:
                return {"command": command, "result": "error", "detail": str(exc)}
            self.server.tps_asked_at = time.time()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                await asyncio.sleep(PROBE_INTERVAL)
                for line in self.server.console.since(start_seq, limit=200):
                    sig = extract_signals(line)
                    if sig.tps is not None or sig.mspt is not None:
                        return {
                            "command": command,
                            "result": "ok",
                            "detail": line.message or line.raw,
                            "tps": sig.tps,
                            "mspt": sig.mspt,
                        }
                    if sig.unknown_command:
                        return {
                            "command": command,
                            "result": "rejected",
                            "detail": "The server does not recognise this command.",
                        }
            return {
                "command": command,
                "result": "silent",
                "detail": f"No TPS or MSPT figures appeared within {timeout:.0f} seconds.",
            }

    async def detect(self) -> dict[str, Any]:
        """Find a working command. Runs once per server start."""
        mode = self.mode()
        self.status_data.update(
            state="detecting",
            tried=[],
            command=None,
            message="Checking which TPS command this server supports…",
        )
        self._publish_status()

        if mode == "disabled":
            self.status_data.update(
                state="disabled",
                detection=None,
                message="TPS monitoring is turned off (monitor.tps_command is empty).",
            )
            self._publish_status()
            return self.status()

        await self.bus.publish(
            Event(
                type="tps_detection_started",
                message="Detecting the TPS command",
                data={"mode": mode},
            )
        )
        if mode == "manual":
            order = [self.configured_command() or ""]
        else:
            remembered = (self.db.get_setting(SETTING_KEY) or {}).get("command")
            order = candidates_for(self.server.mc_version, remembered, self.server.tps_candidates)

        for command in order:
            if self.server.state.value != "ONLINE":
                break
            result = await self.probe(command)
            self.status_data["tried"].append(
                {"command": command, "result": result["result"], "detail": result["detail"]}
            )
            log.info("tps probe %r: %s", command, result["result"])
            if result["result"] == "ok":
                remembered = (self.db.get_setting(SETTING_KEY) or {}).get("command")
                detection = (
                    "manual"
                    if mode == "manual"
                    else ("remembered" if command == remembered else "automatic")
                )
                self.status_data.update(
                    state="active",
                    command=command,
                    detection=detection,
                    detected_at=time.time(),
                    message=f"Reading TPS with '{command}'.",
                )
                self.server.tps_source = command
                self._publish_status()
                if mode == "auto":
                    self.db.set_setting(
                        SETTING_KEY,
                        {
                            "command": command,
                            "minecraft_version": self.server.mc_version,
                            "detected_at": time.time(),
                        },
                    )
                await self.bus.publish(
                    Event(
                        type="tps_command_detected",
                        level="info",
                        message=f"TPS will be read with '{command}'",
                        data={"command": command, "detection": detection},
                    )
                )
                return self.status()

        tried = ", ".join(f"'{t['command']}'" for t in self.status_data["tried"]) or "nothing"
        if mode == "manual":
            message = (
                f"The configured command '{self.configured_command()}' did not report TPS. "
                "Check the command, or switch to automatic detection."
            )
        else:
            message = (
                "The server does not appear to support a TPS command. Tried "
                f"{tried}. Install Carpet or spark, or use Minecraft 1.20.3 or newer."
            )
        self.status_data.update(state="unavailable", command=None, detection=None, message=message)
        self._publish_status()
        await self.bus.publish(
            Event(
                type="tps_detection_failed",
                level="warn",
                message=message,
                data={"tried": self.status_data["tried"]},
            )
        )
        return self.status()

    async def _run(self) -> None:
        try:
            await asyncio.sleep(2)  # let startup chatter settle before probing
            result = await self.detect()
            if result["state"] != "active":
                return  # not retried until the next server start or a manual request
            interval = max(self.config.monitor.tps_poll_interval, 10.0)
            command = result["command"]
            while self.server.state.value == "ONLINE":
                await asyncio.sleep(interval)
                if self.server.state.value != "ONLINE":
                    break
                try:
                    await self.server.send_command(command, internal=True)
                    self.server.tps_asked_at = time.time()
                except Exception:
                    log.debug("tps poll failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("TPS monitor failed")
            self.status_data.update(
                state="unavailable",
                message="TPS detection hit an unexpected error; see the agent log.",
            )
            self._publish_status()

    # ------------------------------------------------------------------ override
    async def set_command(self, value: str) -> dict[str, Any]:
        """Set a manual command, "auto", or "" to disable. Saved to config.yaml."""
        value = (value or "").strip()
        if value.lower() not in ("", "auto", "off"):
            try:
                validate(value)  # a Minecraft command, and not one that needs confirmation
            except CommandError as exc:
                raise ValueError(f"'{value}' cannot be used as the TPS command: {exc}") from exc
        self.config.set("monitor.tps_command", value or "off")
        try:
            self.config.save()
        except OSError as exc:
            raise ValueError(f"The setting could not be saved to config.yaml: {exc}") from exc
        self.server.tps = self.server.mspt = None
        self.server.tps_source = None
        if self.server.state.value == "ONLINE":
            self.begin()
        else:
            self.reset_status()
        return self.status()

    async def redetect(self) -> dict[str, Any]:
        if self.server.state.value != "ONLINE":
            raise ValueError("The server must be online to detect its TPS command.")
        self.db.set_setting(SETTING_KEY, None)
        self.begin()
        return self.status()
