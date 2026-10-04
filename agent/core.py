"""AgentCore wires the subsystems together and owns their lifecycle.

The object graph is intentionally flat: one server supervisor, one of each
manager, one event bus. Multi-server support later means holding a dict of
ServerContext objects here; everything below already takes server_id as a
parameter and stores it on every row.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .backups.manager import BackupManager
from .database.db import Database
from .events import Event, EventBus
from .minecraft.crash import CrashReporter
from .minecraft.process import MinecraftServer
from .mods.manager import ModManager
from .monitoring.metrics import MetricsMonitor
from .monitoring.players import PlayerTracker
from .monitoring.tps import TpsMonitor
from .notifications.dispatcher import Notifier
from .scheduler.scheduler import Scheduler
from .security.auth import AuthManager

log = logging.getLogger("msc.core")


class AgentCore:
    def __init__(self, config):
        self.config = config
        self.config.ensure_dirs()
        self.started_at = time.time()
        self.bus = EventBus()
        self.db = Database(config.database_path)
        self.db.register_server(
            config.server.id,
            config.server.name,
            str(config.server_dir),
        )
        self.server = MinecraftServer(config, self.bus, self.db)
        self.players = PlayerTracker(config, self.bus, self.db, self.server.server_id)
        self.metrics = MetricsMonitor(config, self.bus, self.db, self.server)
        self.tps = TpsMonitor(config, self.bus, self.db, self.server)
        self.mods = ModManager(config, self.bus, self.db, self.server)
        self.backups = BackupManager(config, self.bus, self.db, self.server)
        self.crashes = CrashReporter(config, self.db, self.server, self.metrics,
                                     self.players, self.mods)
        self.notifier = Notifier(config, self.bus, self.db, self.server, self.metrics)
        self.scheduler = Scheduler(config, self.bus, self.db, self.server,
                                   self.backups, self.notifier)
        self.auth = AuthManager(config, self.db, self.bus)

        self.server.signal_hook = self.players.handle_signals
        self.server.crash_hook = self.crashes.collect
        self.server.maintenance = config.maintenance.enabled

        self.bus.subscribe(self._persist_event)
        self.bus.subscribe(self.notifier.handle)
        self.bus.subscribe(self.tps.handle)
        self._update_task: asyncio.Task | None = None
        self._cert_task: asyncio.Task | None = None
        self._cert_alerted: str | None = None

    # ------------------------------------------------------------------
    async def _persist_event(self, event: Event) -> None:
        if event.type in ("console", "metrics"):
            return  # far too chatty for the database; these live in files/metrics
        try:
            self.db.add_event(self.server.server_id, event.type, event.message,
                              level=event.level, data=event.data or None)
        except Exception:  # pragma: no cover
            log.exception("could not persist event %s", event.type)
        if event.type in ("server_stopped", "server_crashed"):
            try:
                await self.players.clear_online()
            except Exception:  # pragma: no cover
                log.exception("could not clear the online player list")

    # ------------------------------------------------------------------
    async def start(self) -> None:
        # Establish facts before the dashboard can ask for them, so the first
        # status it sees is verified rather than assumed.
        self.server.verify_state()
        self.server.detect_java()
        if self.server.state.value == "OFFLINE":
            # Nothing is running, so "nobody is online" is a verified fact.
            await self.players.clear_online()
        self.metrics.start(player_source=self.players.online)
        self.tps.start()
        self.scheduler.seed_defaults()
        self.scheduler.start()
        self._update_task = asyncio.create_task(self._update_check_loop(), name="mod-updates")
        self._cert_task = asyncio.create_task(self._certificate_watch_loop(), name="cert-watch")
        await self.bus.publish(Event(type="agent_started", level="success",
                                     message="Server agent started"))
        if self.config.server.autostart_minecraft:
            from .minecraft.process import ServerError
            try:
                await self.server.start(actor="agent-autostart")
            except ServerError as exc:
                await self.bus.publish(Event(type="autostart_failed", level="error",
                                             message=f"Automatic start failed: {exc}"))

    async def _update_check_loop(self) -> None:
        hours = self.config.mods.update_check_hours
        if hours <= 0:
            return
        await asyncio.sleep(60)
        while True:
            try:
                updates = await self.mods.check_updates()
                if updates:
                    await self.bus.publish(Event(
                        type="mod_updates_available", level="info",
                        message=f"{len(updates)} mod update(s) available",
                        data={"updates": updates[:10]},
                    ))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("mod update check failed", exc_info=True)
            await asyncio.sleep(hours * 3600)


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
            await self.bus.publish(Event(
                type="certificate_expiring",
                level="error" if severity == "critical" else "warn",
                message=(f"TLS certificate expires in {days:.0f} days"
                         if days is not None else "TLS certificate expiry could not be read"),
                data={"days_remaining": days, "severity": severity,
                      "certificate": status.get("certificate_path"),
                      "renew": "python -m installer.make_certs --renew"},
            ))
        elif severity == "ok":
            self._cert_alerted = None
        if not status.get("parsed") and self._cert_alerted != "unreadable":
            self._cert_alerted = "unreadable"
            await self.bus.publish(Event(
                type="certificate_problem", level="error",
                message="The TLS certificate could not be read, so its expiry is unknown",
                data={"error": status.get("parse_error")},
            ))
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
        for task in (self._update_task, self._cert_task):
            if task:
                task.cancel()
        await self.metrics.stop()
        await self.tps.stop()
        await self.scheduler.stop()
        await self.mods.close()
        await self.server.shutdown()
        await self.notifier.stop()
        self.db.close()

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
        status["agent"] = {
            "started_at": self.started_at,
            "uptime": time.time() - self.started_at,
            "version": "1.0.0",
            "database_version": self.db.version,
            "maintenance": self.server.maintenance,
            "maintenance_message": self.config.maintenance.message,
        }
        return status

    def set_maintenance(self, enabled: bool, user: str = "system") -> dict[str, Any]:
        self.server.maintenance = bool(enabled)
        self.config.set("maintenance.enabled", bool(enabled))
        self.db.audit("maintenance_mode", user=user, detail="on" if enabled else "off")
        self.bus.publish_soon(Event(
            type="maintenance_mode",
            level="warn" if enabled else "info",
            message=("Maintenance mode is on. "
                     + self.config.maintenance.message) if enabled
                    else "Maintenance mode is off",
            data={"enabled": bool(enabled)},
        ))
        return {"maintenance": self.server.maintenance}
