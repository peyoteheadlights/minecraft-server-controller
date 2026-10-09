"""Notifications: Discord webhooks, SMTP email and phone alerts.

Nothing in this module may take the agent down. Every send is wrapped, every
failure is recorded in notifications_log and published as an event, and the
caller never sees an exception.

Alerts are queued and sent from the notifier's own background task, so the
event bus (and the console reader that publishes on it) never waits on a slow
Discord or SMTP server.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx

from ..events import Event, EventBus
from . import push

log = logging.getLogger("msc.notify")

# A test alert lands on a lock screen with no context around it, so it says
# it is a test rather than borrowing a real event's title ("Survival is online").
PUSH_TEST_TITLE = "Test alert"

# event type -> (settings key, emoji, colour, title). "{server}" in a title is
# replaced with the server's name, so an alert reads "Survival crashed".
EVENT_MAP: dict[str, tuple[str, str, int, str]] = {
    "server_started": ("server_started", "🟢", 0x3BA55D, "{server} is online"),
    "server_stopped": ("server_stopped", "⚪", 0x9AA0A6, "{server} stopped"),
    "server_crashed": ("server_crashed", "🔴", 0xED4245, "{server} crashed"),
    "server_restarted": ("server_restarted", "🔁", 0x5865F2, "{server} restarted"),
    "server_recovered": ("server_recovered", "🟢", 0x3BA55D, "{server} recovered"),
    "crash_loop": ("server_crashed", "🛑", 0xED4245, "{server}: automatic restart disabled"),
    "restart_scheduled": (
        "server_restarted",
        "⏳",
        0xFAA61A,
        "{server}: automatic restart scheduled",
    ),
    "restart_cancelled": (
        "server_restarted",
        "✋",
        0x9AA0A6,
        "{server}: automatic restart cancelled",
    ),
    "player_joined": ("player_joined", "👋", 0x5865F2, "Player joined {server}"),
    "player_left": ("player_left", "🚪", 0x9AA0A6, "Player left {server}"),
    "high_ram": ("high_ram", "⚠️", 0xFAA61A, "High memory use"),
    "high_cpu": ("high_cpu", "⚠️", 0xFAA61A, "High CPU use"),
    "low_disk": ("low_disk", "⚠️", 0xFAA61A, "Low disk space for {server}"),
    "low_tps": ("low_tps", "⚠️", 0xFAA61A, "{server}: game running slow"),
    "high_mspt": ("high_mspt", "⚠️", 0xFAA61A, "{server}: game falling behind"),
    "backup_completed": ("backup_completed", "💾", 0x3BA55D, "{server}: backup finished"),
    "backup_failed": ("backup_failed", "❌", 0xED4245, "{server}: backup failed"),
    "mod_installed": ("mod_installed", "📦", 0x3BA55D, "{server}: mod installed"),
    "mod_removed": ("mod_removed", "🗑️", 0xFAA61A, "{server}: mod removed"),
    "mod_updated": ("mod_updated", "⬆️", 0x3BA55D, "{server}: mod updated"),
    "mod_rolled_back": ("mod_updated", "↩️", 0xFAA61A, "{server}: mod rolled back"),
    "mod_dependency_problem": (
        "mod_dependency_problem",
        "⚠️",
        0xFAA61A,
        "{server}: mod dependency problem",
    ),
    "auth_failure": ("auth_failure", "🔒", 0xED4245, "Failed sign-in attempt"),
    "maintenance_mode": ("maintenance_mode", "🔧", 0x5865F2, "Maintenance mode"),
    "certificate_expiring": (
        "certificate_expiring",
        "🔐",
        0xFAA61A,
        "Secure connection certificate runs out soon",
    ),
    "certificate_problem": (
        "certificate_expiring",
        "🔐",
        0xED4245,
        "Secure connection certificate problem",
    ),
    "update_available": ("app_updates", "⬆️", 0x5865F2, "A new version of the app is out"),
    "update_finished": ("app_updates", "✅", 0x3BA55D, "The app was updated"),
    "update_failed": ("app_updates", "❌", 0xED4245, "The app's update didn't work"),
    "server_added": ("servers_changed", "➕", 0x5865F2, "Server added: {server}"),
    "server_removed": ("servers_changed", "➖", 0x9AA0A6, "Server removed: {server}"),
    "server_duplicated": ("servers_changed", "➕", 0x5865F2, "Server copied: {server}"),
    "game_settings_changed": (
        "game_settings_changed",
        "⚙️",
        0x5865F2,
        "{server}: game settings changed",
    ),
    "player_action": ("player_managed", "👤", 0x5865F2, "{server}: player list changed"),
    "modpack_imported": ("modpack_imported", "📦", 0x3BA55D, "{server}: modpack imported"),
    "cpu_cores_failed": (
        "cpu_cores_failed",
        "⚠️",
        0xFAA61A,
        "{server}: CPU core limit not applied",
    ),
    "autosleep_stopped": ("autosleep", "😴", 0x9AA0A6, "{server} stopped: nobody was playing"),
    "backup_copy_failed": (
        "backup_copy_failed",
        "❌",
        0xED4245,
        "{server}: backup's second copy failed",
    ),
    "world_imported": ("world_imported", "🌍", 0x3BA55D, "{server}: world imported"),
    "helper_added": ("helper_added", "👤", 0x5865F2, "Helper added"),
    "helper_removed": ("helper_removed", "👤", 0xFAA61A, "Helper removed"),
}


THROTTLED = {
    "high_ram",
    "high_cpu",
    "low_disk",
    "low_tps",
    "high_mspt",
    "auth_failure",
    "certificate_expiring",
}


# The dashboard page an alert is about, so tapping it on a phone opens that
# page of that server (agent/web/sw.js). Anything not listed opens the
# server's Overview, or the server list for an app-wide alert.
ALERT_PAGES = {
    "server_crashed": "crashes",
    "crash_loop": "crashes",
    "backup_completed": "backups",
    "backup_failed": "backups",
    "backup_copy_failed": "backups",
    "mod_installed": "mods",
    "mod_removed": "mods",
    "mod_updated": "mods",
    "mod_dependency_problem": "mods",
    "player_joined": "players",
    "player_left": "players",
    "player_managed": "players",
    "low_tps": "performance",
    "high_mspt": "performance",
    "high_ram": "performance",
    "high_cpu": "performance",
    "low_disk": "performance",
    "game_settings_changed": "game-settings",
    "world_imported": "world",
    "auth_failure": "security",
    "certificate_expiring": "security",
    "helper_added": "helpers",
    "update_available": "app-settings",
    "update_finished": "app-settings",
    "update_failed": "app-settings",
}
APP_PAGES = {"security", "helpers", "app-settings"}


def alert_page(event: Event) -> str:
    page = ALERT_PAGES.get(event.type)
    if page in APP_PAGES:
        return page
    if event.server_id:
        return page or "dashboard"
    return page or "servers"


def alert_link(event: Event) -> str:
    """The dashboard address for an alert, like /#survival/crashes."""
    from urllib.parse import quote

    page = alert_page(event)
    if event.server_id and page not in APP_PAGES and page != "servers":
        return f"/#{quote(event.server_id, safe='')}/{page}"
    return f"/#{page}"


class Notifier:
    # Alerts waiting to be sent. If the network is down for long enough to
    # fill this, the oldest waiting alert is dropped (and logged).
    QUEUE_SIZE = 100

    def __init__(self, config, bus: EventBus, db, server=None, metrics=None, servers=None):
        self.config = config
        self.bus = bus
        self.db = db
        # One server's supervisor and metrics, when the notifier is built for
        # a single server (as the tests do). With several, ``servers`` maps
        # each server id to its ServerContext and is consulted per event.
        self.server = server
        self.metrics = metrics
        self.servers = servers
        # (server id, event type) -> when that alert was last sent, so the
        # cooldown applies to each server separately.
        self._last_sent: dict[tuple[str | None, str], float] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.QUEUE_SIZE)
        self._worker: asyncio.Task | None = None

    # ------------------------------------------------------------------
    def enabled_for(self, event_type: str) -> bool:
        mapping = EVENT_MAP.get(event_type)
        if not mapping:
            return False
        key = mapping[0]
        return self.config.notifications.event_enabled(key)

    def _log(self, channel: str, event: str, status: str, detail: str = "") -> None:
        try:
            self.db.insert(
                "notifications_log",
                {
                    "ts": time.time(),
                    "channel": channel,
                    "event": event,
                    "status": status,
                    "detail": detail[:500],
                },
            )
        except Exception:  # pragma: no cover
            log.exception("could not record notification result")

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM notifications_log ORDER BY ts DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------
    def _context(self, event: Event):
        if self.servers is not None and event.server_id is not None:
            return self.servers.get(event.server_id)
        return None

    def server_name(self, event: Event) -> str:
        ctx = self._context(event)
        if ctx is not None:
            return ctx.name
        if event.server_id is not None and self.servers is not None:
            return event.data.get("server_name") or event.server_id
        return self.config.server.name

    def _metrics_for(self, event: Event):
        ctx = self._context(event)
        return ctx.metrics if ctx is not None else self.metrics

    def _auto_restart_for(self, event: Event) -> bool:
        ctx = self._context(event)
        return (ctx.config if ctx is not None else self.config).monitor.auto_restart

    def title(self, event: Event) -> tuple[str, int, str]:
        """(emoji, colour, title) with the server named."""
        emoji, colour, title = EVENT_MAP.get(event.type, (event.type, "", 0x5865F2, event.type))[1:]
        return emoji, colour, title.replace("{server}", self.server_name(event))

    # ------------------------------------------------------------------
    def _fields(self, event: Event) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        data = event.data or {}
        if event.type == "server_started" and data.get("startup_seconds"):
            fields.append(
                {
                    "name": "Startup time",
                    "value": f"{data['startup_seconds']:.1f} s",
                    "inline": True,
                }
            )
        if event.type == "server_crashed":
            analysis = data.get("analysis") or {}
            fields.append(
                {"name": "Exit code", "value": str(data.get("exit_code")), "inline": True}
            )
            if analysis.get("category"):
                fields.append(
                    {
                        "name": f"{str(analysis.get('confidence', 'possible')).title()} cause",
                        "value": f"{analysis['category']}\n{analysis.get('summary', '')}"[:1000],
                        "inline": False,
                    }
                )
            if analysis.get("evidence"):
                evidence = "\n".join(analysis["evidence"][-3:])[:900]
                fields.append({"name": "Evidence", "value": f"```{evidence}```", "inline": False})
            if data.get("players_online"):
                fields.append(
                    {
                        "name": "Players online at the time",
                        "value": ", ".join(data["players_online"])[:200],
                        "inline": False,
                    }
                )
            auto = self._auto_restart_for(event)
            fields.append(
                {
                    "name": "Automatic restart",
                    "value": "Enabled" if auto else "Disabled",
                    "inline": True,
                }
            )
        metrics = self._metrics_for(event)
        if metrics and event.type in ("server_crashed", "high_ram", "high_cpu", "low_disk"):
            snap = metrics.last or {}
            if snap:
                disk_free = snap.get("disk_free_gb")
                disk = f"{disk_free:.1f} GB free" if disk_free is not None else "unknown"
                fields.append(
                    {
                        "name": "Machine",
                        "value": (
                            f"RAM {snap.get('ram_used_mb', 0) / 1024:.1f} / "
                            f"{snap.get('ram_total_mb', 0) / 1024:.1f} GB\n"
                            f"CPU {snap.get('cpu_percent', 0):.0f}%\n"
                            f"Disk {disk}"
                        ),
                        "inline": True,
                    }
                )
        for key in ("username", "value", "threshold", "name", "size_bytes"):
            if key in data and not any(f["name"].lower() == key for f in fields):
                value = data[key]
                if key == "size_bytes":
                    value = f"{float(value) / 1024**3:.2f} GB"
                fields.append(
                    {
                        "name": key.replace("_", " ").title(),
                        "value": str(value)[:200],
                        "inline": True,
                    }
                )
        return fields[:8]

    # ------------------------------------------------------------------
    async def send_discord(self, event: Event) -> bool:
        webhook = self.config.discord_webhook
        if not webhook:
            self._log("discord", event.type, "skipped", "No webhook URL is configured")
            return False
        emoji, colour, title = self.title(event)
        footer = (
            self.server_name(event)
            if event.server_id is not None or self.servers is None
            else "Minecraft Server Control"
        )
        payload = {
            "username": "Minecraft Control",
            "embeds": [
                {
                    "title": f"{emoji} {title}",
                    "description": event.message[:2000] or title,
                    "color": colour,
                    "fields": self._fields(event),
                    "footer": {"text": f"{footer} · {time.strftime('%d %b %H:%M')}"},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(event.ts)),
                }
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(webhook, json=payload)
            if response.status_code >= 400:
                self._log("discord", event.type, "failed", f"HTTP {response.status_code}")
                await self._report_failure("Discord", f"HTTP {response.status_code}")
                return False
            self._log("discord", event.type, "sent")
            return True
        except (httpx.HTTPError, OSError) as exc:
            self._log("discord", event.type, "failed", str(exc))
            await self._report_failure("Discord", str(exc))
            return False

    # ------------------------------------------------------------------
    def _build_email(self, event: Event) -> EmailMessage:
        cfg = self.config.notifications.email
        emoji, _, title = self.title(event)
        message = EmailMessage()
        message["Subject"] = f"{emoji} {title}"
        message["From"] = cfg.from_address or self.config.smtp_username
        message["To"] = ", ".join(cfg.to_addresses)
        lines = [title, "", event.message, ""]
        data = event.data or {}
        analysis = data.get("analysis") or {}
        if analysis:
            lines += [
                f"{str(analysis.get('confidence', 'possible')).title()} cause: {analysis.get('category')}",
                analysis.get("summary", ""),
                "",
                "Evidence:",
                *analysis.get("evidence", [])[-6:],
                "",
            ]
        for key, value in data.items():
            if key in ("analysis", "console_tail", "metrics", "error_lines", "warn_lines"):
                continue
            lines.append(f"{key}: {value}")
        lines += ["", f"Sent by Minecraft Server Control at {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        message.set_content("\n".join(str(line) for line in lines))

        if cfg.attach_crash_report and data.get("crash_report"):
            self._attach(message, Path(data["crash_report"]))
        if cfg.attach_log_tail and data.get("console_file"):
            self._attach(message, Path(data["console_file"]))
        return message

    @staticmethod
    def _attach(message: EmailMessage, path: Path, max_bytes: int = 2 * 1024 * 1024) -> None:
        try:
            if not path.is_file():
                return
            data = path.read_bytes()[:max_bytes]
            message.add_attachment(data, maintype="text", subtype="plain", filename=path.name)
        except OSError:  # pragma: no cover
            log.warning("could not attach %s", path, exc_info=True)

    def _send_email_sync(self, message: EmailMessage) -> None:
        cfg = self.config.notifications.email
        host = cfg.host
        port = cfg.port
        timeout = 25
        server: smtplib.SMTP
        if cfg.use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        try:
            server.ehlo()
            if cfg.use_tls and not cfg.use_ssl:
                server.starttls()
                server.ehlo()
            if self.config.smtp_username:
                server.login(self.config.smtp_username, self.config.smtp_password)
            server.send_message(message)
        finally:
            try:
                server.quit()
            except Exception:  # pragma: no cover
                pass

    async def send_email(self, event: Event) -> bool:
        cfg = self.config.notifications.email
        if not cfg.host or not cfg.to_addresses:
            self._log("email", event.type, "skipped", "SMTP host or recipient is not configured")
            return False
        try:
            message = self._build_email(event)
            await asyncio.to_thread(self._send_email_sync, message)
            self._log("email", event.type, "sent")
            return True
        except Exception as exc:
            self._log("email", event.type, "failed", str(exc))
            await self._report_failure("Email", str(exc))
            return False

    # ------------------------------------------------------------------
    async def send_push(self, event: Event, title: str | None = None) -> bool:
        """One short message to every phone signed up for alerts.

        A phone the push service says is gone is forgotten; every other
        failure is recorded and the phone stays on the list.
        """
        config = self.config
        if not config.vapid_public_key or not config.vapid_private_key:
            self._log("push", event.type, "skipped", "No phone-alert keys are set up")
            return False
        subscriptions = push.subscriptions(self.db)
        if not subscriptions:
            self._log("push", event.type, "skipped", "No phone has signed up for alerts")
            return False
        emoji, _colour, event_title = self.title(event)
        heading = title or f"{emoji} {event_title}"
        message = {
            "title": heading,
            "body": (event.message or event_title)[:300],
            "event": event.type,
            "level": event.level,
            "server_id": event.server_id,
            "ts": event.ts,
            # Tapping the alert opens this page of this server.
            "page": alert_page(event),
            "url": alert_link(event),
        }
        sent = 0
        for subscription in subscriptions:
            result = await push.send(
                subscription,
                message,
                config.vapid_public_key,
                config.vapid_private_key,
                config.push_subject,
            )
            push.record_result(self.db, subscription.endpoint, result)
            if result.ok:
                sent += 1
                self._log("push", event.type, "sent", subscription.label)
                continue
            if result.gone:
                push.forget(self.db, subscription.endpoint)
                self._log("push", event.type, "dropped", result.detail)
                continue
            self._log("push", event.type, "failed", result.detail)
            await self._report_failure("Phone alerts", result.detail)
        return sent > 0

    async def _report_failure(self, channel: str, detail: str) -> None:
        try:
            await self.bus.publish(
                Event(
                    type="notification_failed",
                    level="warn",
                    message=f"{channel} notification could not be sent: {detail}"[:300],
                    data={"channel": channel},
                )
            )
        except Exception:  # pragma: no cover
            log.exception("could not publish notification failure")

    # ------------------------------------------------------------------
    async def handle(self, event: Event) -> None:
        """Event bus subscriber. Queues the alert and returns at once; never raises."""
        try:
            if event.type not in EVENT_MAP or not self.enabled_for(event.type):
                return
            min_interval = self.config.notifications.min_interval_seconds
            key = (event.server_id, event.type)
            if event.type in THROTTLED:
                if time.time() - self._last_sent.get(key, 0) < min_interval:
                    return
            self._last_sent[key] = time.time()
            if self._queue.full():
                dropped = self._queue.get_nowait()
                self._queue.task_done()
                log.warning("notification queue full; dropped %s alert", dropped.type)
            self._queue.put_nowait(event)
            self._ensure_worker()
        except Exception:
            log.exception("notification dispatch failed for %s", event.type)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run(), name="notifier")

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self.deliver(event)
            finally:
                self._queue.task_done()

    async def deliver(self, event: Event) -> None:
        """Send one alert to every enabled channel. Never raises."""
        try:
            tasks = []
            if self.config.notifications.discord_enabled:
                tasks.append(self.send_discord(event))
            if self.config.notifications.email_enabled:
                tasks.append(self.send_email(event))
            if self.config.notifications.push_enabled:
                tasks.append(self.send_push(event))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            log.exception("notification dispatch failed for %s", event.type)

    async def drain(self) -> None:
        """Wait until every queued alert has been attempted."""
        await self._queue.join()

    async def stop(self, drain_timeout: float = 10.0) -> None:
        """Give queued alerts a short chance to go out, then stop the sender."""
        if self._worker and not self._worker.done() and drain_timeout > 0:
            try:
                await asyncio.wait_for(self.drain(), drain_timeout)
            except TimeoutError:
                log.warning("stopping with %d alert(s) unsent", self._queue.qsize())
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    async def test(self, channel: str) -> dict[str, Any]:
        event = Event(
            type="server_started",
            level="success",
            message="Test notification from Minecraft Server Control",
            data={"startup_seconds": 0.0},
        )
        if channel == "discord":
            ok = await self.send_discord(event)
        elif channel == "email":
            ok = await self.send_email(event)
        elif channel == "push":
            ok = await self.send_push(event, title=PUSH_TEST_TITLE)
        else:
            raise ValueError("Pick Discord, email or phone alerts.")
        return {"channel": channel, "sent": ok}
