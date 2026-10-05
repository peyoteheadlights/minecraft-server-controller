"""AgentCore wires the subsystems together and owns their lifecycle.

Shared by every server: the event bus, the database (and its event writer),
the notifier, sign-in, the job tracker and the port manager.

Per server: a ServerContext holding that server's process supervisor,
player tracker, metrics, TPS monitor, mods, backups, crash reporter and
scheduler. AgentCore keeps them in ``servers``, keyed by server id, in the
order config.yaml lists them. The first one is what the unprefixed API
routes and ``core.server`` refer to.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from . import __version__, colors
from .backups.manager import BackupManager
from .config import ConfigError
from .database.db import Database, ServerDb
from .database.event_writer import EventWriter
from .events import AGENT_SCOPE, Event, EventBus, ServerBus
from .jobs import JobConflict, JobHandle, JobTracker
from .minecraft.crash import CrashReporter
from .minecraft.process import MinecraftServer, ServerError
from .mods.manager import ModManager
from .monitoring.metrics import MetricsMonitor
from .monitoring.players import PlayerTracker
from .monitoring.tps import TpsMonitor
from .notifications.dispatcher import Notifier
from .ports import PortManager
from .scheduler.scheduler import Scheduler
from .security.auth import AuthManager

log = logging.getLogger("msc.core")


class UnknownServer(LookupError):
    """No server with that id is registered."""


class ServerContext:
    """Everything that belongs to one Minecraft server."""

    def __init__(self, core: AgentCore, server_id: str):
        self.core = core
        self.server_id = server_id
        self.config = core.config.for_server(server_id)
        self.config.ensure_dirs()
        self.bus = ServerBus(core.bus, server_id)
        self.db = ServerDb(core.db, server_id)
        core.db.register_server(
            server_id,
            self.config.server.name,
            str(self.config.server_dir),
            self.config.server.type,
        )
        if not core.db.server_color(server_id):
            taken = [other.color for other in core.servers.values() if other is not self]
            core.db.set_server_color(server_id, colors.next_unused(taken))

        self.server = MinecraftServer(self.config, self.bus, self.db)
        self.players = PlayerTracker(self.config, self.bus, self.db, server_id)
        self.metrics = MetricsMonitor(self.config, self.bus, self.db, self.server)
        self.tps = TpsMonitor(self.config, self.bus, self.db, self.server)
        self.mods = ModManager(self.config, self.bus, self.db, self.server)
        self.backups = BackupManager(self.config, self.bus, self.db, self.server, jobs=core.jobs)
        self.crashes = CrashReporter(
            self.config, self.db, self.server, self.metrics, self.players, self.mods
        )
        self.scheduler = Scheduler(
            self.config, self.bus, self.db, self.server, self.backups, core.notifier
        )

        self.server.signal_hook = self.players.handle_signals
        self.server.crash_hook = self.crashes.collect
        self.server.maintenance = core.config.maintenance.enabled
        self.server.start_guard = lambda: core.ports.start_conflicts(self)
        self.server.start_warnings = lambda: core.ports.start_warnings(self)
        self._update_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return self.config.server.name

    @property
    def color(self) -> str | None:
        return self.core.db.server_color(self.server_id)

    async def mod_change(
        self, title: str, change: Callable[[], Awaitable[Any]], user: str | None = None
    ) -> Any:
        """Run a change to this server's mods as a risky job, so it never
        runs during a restore or another change (and they wait for it)."""
        if self.server.held_by:
            raise JobConflict(
                f"Wait for '{self.server.held_by}' to finish first. A server runs one "
                "change like this at a time."
            )

        async def run(job: JobHandle) -> Any:
            job.step(title)
            return await change()

        _, result = await self.core.jobs.run(
            "mods", f"{title} on {self.name}", run, server_id=self.server_id, risky=True, user=user
        )
        return result

    # ------------------------------------------------------------------
    async def handle(self, event: Event) -> None:
        """This server's own events, passed on by AgentCore."""
        await self.tps.handle(event)
        if event.type in ("server_stopped", "server_crashed"):
            try:
                await self.players.clear_online()
            except Exception:  # pragma: no cover
                log.exception("could not clear the online player list")

    async def start(self) -> None:
        # Establish facts before the dashboard can ask for them, so the first
        # status it sees is verified rather than assumed.
        self.server.verify_state()
        # `java -version` can take seconds on a cold disk; don't block the loop.
        await asyncio.to_thread(self.server.detect_java)
        if self.server.state.value == "OFFLINE":
            # Nothing is running, so "nobody is online" is a verified fact.
            await self.players.clear_online()
        self.metrics.start(player_source=self.players.online)
        self.tps.start()
        self.scheduler.seed_defaults()
        self.scheduler.start()
        self._update_task = asyncio.create_task(
            self._update_check_loop(), name=f"mod-updates-{self.server_id}"
        )

    async def autostart(self) -> None:
        if not self.config.server.autostart_minecraft:
            return
        try:
            await self.server.start(actor="agent-autostart")
        except ServerError as exc:
            await self.bus.publish(
                Event(
                    type="autostart_failed",
                    level="error",
                    message=f"Automatic start failed: {exc}",
                )
            )

    async def _update_check_loop(self) -> None:
        hours = self.config.mods.update_check_hours
        if hours <= 0:
            return
        await asyncio.sleep(60)
        while True:
            try:
                updates = await self.mods.check_updates()
                if updates:
                    await self.bus.publish(
                        Event(
                            type="mod_updates_available",
                            level="info",
                            message=f"{len(updates)} mod update(s) available",
                            data={"updates": updates[:10]},
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("mod update check failed", exc_info=True)
            await asyncio.sleep(hours * 3600)

    async def stop(self) -> None:
        if self._update_task:
            self._update_task.cancel()
        await self.metrics.stop()
        await self.tps.stop()
        await self.scheduler.stop()
        await self.mods.close()
        await self.server.shutdown()

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        status = self.server.status()
        online = self.players.online()
        # None means "not established yet", which the dashboard renders as
        # Unknown. It is not the same as a verified zero.
        status["players_online"] = self.players.online_count()
        status["players_verified"] = self.players.verified
        status["players_source"] = self.players.verified_source
        status["players"] = online
        status["metrics"] = self.metrics.last or self.metrics.snapshot()
        port = self.core.ports.port_of(self)
        status["game_port"] = port.to_dict()
        running = self.core.jobs.risky_job(self.server_id)
        status["job"] = running.to_dict() if running else None
        status["agent"] = self.core.agent_status(self)
        return status

    def summary(self) -> dict[str, Any]:
        """One row of the All servers view: measured facts only."""
        status = self.server.status()
        return {
            "id": self.server_id,
            "name": self.name,
            "color": self.color,
            "state": status["state"],
            "state_verified": status["state_verified"],
            "uptime": status["uptime"],
            "players_online": self.players.online_count(),
            "players_verified": self.players.verified,
            "max_players": self.config.server.max_players,
            "minecraft_version": status["minecraft_version"],
            "game_port": self.core.ports.port_of(self).to_dict(),
            "directory": status["directory"],
            "default": self.server_id == self.core.config.default_server_id,
            "recent_crashes": status["recent_crashes"],
        }


class AgentCore:
    def __init__(self, config):
        self.config = config
        self.config.ensure_dirs()
        self.started_at = time.time()
        self.bus = EventBus()
        self.db = Database(config.database_path)
        self.events = EventWriter(self.db)
        self.auth = AuthManager(config, self.db, self.bus)
        self.jobs = JobTracker(self.db, self.bus)
        self.jobs.mark_interrupted()
        self.ports = PortManager(self)
        self.servers: dict[str, ServerContext] = {}
        self.notifier = Notifier(config, self.bus, self.db, servers=self.servers)
        for server_id in config.server_ids:
            self.servers[server_id] = ServerContext(self, server_id)

        self.bus.subscribe(self._persist_event)
        self.bus.subscribe(self.notifier.handle)
        self.bus.subscribe(self._dispatch)
        self._cert_task: asyncio.Task | None = None
        self._cert_alerted: str | None = None
        self._servers_lock = asyncio.Lock()

    # -- lookup -------------------------------------------------------------
    @property
    def default(self) -> ServerContext:
        return self.servers[self.config.default_server_id]

    def get_server(self, server_id: str) -> ServerContext:
        ctx = self.servers.get(server_id)
        if ctx is None:
            raise UnknownServer(f"There is no server with the id '{server_id}'")
        return ctx

    # The first server's managers, as they were reached before there were
    # several servers. New code should go through a ServerContext.
    @property
    def server(self) -> MinecraftServer:
        return self.default.server

    @property
    def players(self) -> PlayerTracker:
        return self.default.players

    @property
    def metrics(self) -> MetricsMonitor:
        return self.default.metrics

    @property
    def tps(self) -> TpsMonitor:
        return self.default.tps

    @property
    def mods(self) -> ModManager:
        return self.default.mods

    @property
    def backups(self) -> BackupManager:
        return self.default.backups

    @property
    def crashes(self) -> CrashReporter:
        return self.default.crashes

    @property
    def scheduler(self) -> Scheduler:
        return self.default.scheduler

    # ------------------------------------------------------------------
    async def _persist_event(self, event: Event) -> None:
        if event.type in ("console", "metrics", "job"):
            return  # far too chatty for the database; these live elsewhere
        self.events.add(
            event.server_id or AGENT_SCOPE,
            event.type,
            event.message,
            level=event.level,
            data=event.data or None,
        )

    async def _dispatch(self, event: Event) -> None:
        ctx = self.servers.get(event.server_id) if event.server_id else None
        if ctx is not None:
            await ctx.handle(event)

    # ------------------------------------------------------------------
    async def start(self) -> None:
        for ctx in list(self.servers.values()):
            await ctx.start()
        self._cert_task = asyncio.create_task(self._certificate_watch_loop(), name="cert-watch")
        await self.bus.publish(
            Event(type="agent_started", level="success", message="Server agent started")
        )
        for ctx in list(self.servers.values()):
            await ctx.autostart()

    async def check_certificate(self) -> dict:
        """Read the certificate and alert on approaching expiry.

        Source of truth: the certificate file itself. If it cannot be read the
        result is reported as unknown - never as "valid".
        """
        status = self.metrics.certificate_status()
        if not status.get("enabled"):
            return status
        severity = status.get("expiry_severity")
        days = status.get("days_remaining")
        if severity in ("warn", "critical") and self._cert_alerted != severity:
            self._cert_alerted = severity
            await self.bus.publish(
                Event(
                    type="certificate_expiring",
                    level="error" if severity == "critical" else "warn",
                    message=(
                        f"TLS certificate expires in {days:.0f} days"
                        if days is not None
                        else "TLS certificate expiry could not be read"
                    ),
                    data={
                        "days_remaining": days,
                        "severity": severity,
                        "certificate": status.get("certificate_path"),
                        "renew": "python -m installer.make_certs --renew",
                    },
                )
            )
        elif severity == "ok":
            self._cert_alerted = None
        if not status.get("parsed") and self._cert_alerted != "unreadable":
            self._cert_alerted = "unreadable"
            await self.bus.publish(
                Event(
                    type="certificate_problem",
                    level="error",
                    message="The TLS certificate could not be read, so its expiry is unknown",
                    data={"error": status.get("parse_error")},
                )
            )
        return status

    async def _certificate_watch_loop(self) -> None:
        if not self.config.tls_enabled:
            return
        hours = self.config.tls.check_interval_hours
        await asyncio.sleep(5)
        while True:
            try:
                await self.check_certificate()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("certificate check failed")
            await asyncio.sleep(max(hours, 0.25) * 3600)

    async def stop(self) -> None:
        await self.bus.publish(Event(type="agent_stopping", message="Server agent stopping"))
        if self._cert_task:
            self._cert_task.cancel()
        await self.jobs.stop()
        for ctx in list(self.servers.values()):
            await ctx.stop()
        await self.notifier.stop()
        await self.events.stop()
        self.db.close()

    # -- adding and removing servers ----------------------------------------
    async def add_server(self, entry: dict[str, Any], user: str = "system") -> ServerContext:
        """Register a server folder and start supervising it (Minecraft itself
        is not started). The entry has already been validated by the route."""
        async with self._servers_lock:
            settings = self.config.add_server(entry)
            try:
                self.config.save()
            except OSError as exc:
                self.config.remove_server(settings.id)
                raise ConfigError(f"The server list could not be saved: {exc}") from exc
            ctx = ServerContext(self, settings.id)
            self.servers[settings.id] = ctx
            await ctx.start()
        self.db.audit("server_add", user=user, target=settings.id, server_id=settings.id)
        await ctx.bus.publish(
            Event(
                type="server_added",
                level="success",
                message=f"Added the server {settings.name}",
                data={"server_name": settings.name, "directory": settings.directory},
            )
        )
        return ctx

    async def remove_server(self, server_id: str, user: str = "system") -> dict[str, Any]:
        """Stop supervising a server and take it off the list. Its folder,
        world, backups and history are left exactly where they are."""
        async with self._servers_lock:
            ctx = self.get_server(server_id)
            if ctx.server.running:
                raise ServerError(f"Stop {ctx.name} before removing it from the list")
            if self.jobs.risky_job(server_id):
                raise ServerError(f"Wait for {ctx.name}'s running job to finish first")
            name, directory = ctx.name, str(ctx.config.server_dir)
            # Stop supervising first: the managers still read this server's
            # settings while they shut down.
            await ctx.stop()
            entry = self.config.remove_server(server_id)
            try:
                self.config.save()
            except OSError as exc:
                self.config.add_server(entry)
                self.servers[server_id] = restored = ServerContext(self, server_id)
                await restored.start()
                raise ConfigError(f"The server list could not be saved: {exc}") from exc
            del self.servers[server_id]
        self.db.audit("server_remove", user=user, target=server_id, server_id=server_id)
        await self.bus.publish(
            Event(
                type="server_removed",
                level="warn",
                message=f"Removed {name} from the list. Its folder was not touched.",
                data={"server_name": name, "directory": directory},
                server_id=server_id,
            )
        )
        return {"removed": server_id, "name": name, "directory": directory}

    # ------------------------------------------------------------------
    def agent_status(self, ctx: ServerContext | None = None) -> dict[str, Any]:
        maintenance = ctx.server.maintenance if ctx else self.config.maintenance.enabled
        return {
            "started_at": self.started_at,
            "uptime": time.time() - self.started_at,
            "version": __version__,
            "database_version": self.db.version,
            "maintenance": maintenance,
            "maintenance_message": self.config.maintenance.message,
            "data_directory": str(self.config.data_dir),
            "servers": len(self.servers),
        }

    def status(self) -> dict[str, Any]:
        """The first server's status (what /api/status has always returned)."""
        return self.default.status()

    def set_maintenance(self, enabled: bool, user: str = "system") -> dict[str, Any]:
        for ctx in self.servers.values():
            ctx.server.maintenance = bool(enabled)
        self.config.set("maintenance.enabled", bool(enabled))
        self.db.audit("maintenance_mode", user=user, detail="on" if enabled else "off")
        self.bus.publish_soon(
            Event(
                type="maintenance_mode",
                level="warn" if enabled else "info",
                message=("Maintenance mode is on. " + self.config.maintenance.message)
                if enabled
                else "Maintenance mode is off",
                data={"enabled": bool(enabled)},
            )
        )
        return {"maintenance": bool(enabled)}
