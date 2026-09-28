"""Notifications: Discord webhooks and SMTP email.

Nothing in this module may take the agent down. Every send is wrapped, every
failure is recorded in notifications_log and published as an event, and the
caller never sees an exception.
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

log = logging.getLogger("msc.notify")

# event type -> (settings key, emoji, colour, title)
EVENT_MAP: dict[str, tuple[str, str, int, str]] = {
    "server_started": ("server_started", "🟢", 0x3BA55D, "Minecraft server online"),
    "server_stopped": ("server_stopped", "⚪", 0x9AA0A6, "Minecraft server stopped"),
    "server_crashed": ("server_crashed", "🔴", 0xED4245, "Minecraft server crash"),
    "server_restarted": ("server_restarted", "🔁", 0x5865F2, "Minecraft server restarted"),
    "server_recovered": ("server_recovered", "🟢", 0x3BA55D, "Minecraft server recovered"),
    "crash_loop": ("server_crashed", "🛑", 0xED4245, "Automatic restart disabled"),
    "restart_scheduled": ("server_restarted", "⏳", 0xFAA61A, "Automatic restart scheduled"),
    "restart_cancelled": ("server_restarted", "✋", 0x9AA0A6, "Automatic restart cancelled"),
    "player_joined": ("player_joined", "👋", 0x5865F2, "Player joined"),
    "player_left": ("player_left", "🚪", 0x9AA0A6, "Player left"),
    "high_ram": ("high_ram", "⚠️", 0xFAA61A, "High memory use"),
    "high_cpu": ("high_cpu", "⚠️", 0xFAA61A, "High CPU use"),
    "low_disk": ("low_disk", "⚠️", 0xFAA61A, "Low disk space"),
    "low_tps": ("low_tps", "⚠️", 0xFAA61A, "Low TPS"),
    "high_mspt": ("high_mspt", "⚠️", 0xFAA61A, "High MSPT"),
    "backup_completed": ("backup_completed", "💾", 0x3BA55D, "Backup finished"),
    "backup_failed": ("backup_failed", "❌", 0xED4245, "Backup failed"),
    "mod_installed": ("mod_installed", "📦", 0x3BA55D, "Mod installed"),
    "mod_removed": ("mod_removed", "🗑️", 0xFAA61A, "Mod removed"),
    "mod_updated": ("mod_updated", "⬆️", 0x3BA55D, "Mod updated"),
    "mod_rolled_back": ("mod_updated", "↩️", 0xFAA61A, "Mod rolled back"),
    "mod_dependency_problem": ("mod_dependency_problem", "⚠️", 0xFAA61A, "Mod dependency problem"),
    "auth_failure": ("auth_failure", "🔒", 0xED4245, "Failed sign-in attempt"),
    "maintenance_mode": ("maintenance_mode", "🔧", 0x5865F2, "Maintenance mode"),
    "certificate_expiring": ("certificate_expiring", "🔐", 0xFAA61A, "TLS certificate expiring"),
    "certificate_problem": ("certificate_expiring", "🔐", 0xED4245, "TLS certificate problem"),
}


class Notifier:
    def __init__(self, config, bus: EventBus, db, server=None, metrics=None):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self.metrics = metrics
        self._last_sent: dict[str, float] = {}

    # ------------------------------------------------------------------
    def enabled_for(self, event_type: str) -> bool:
        mapping = EVENT_MAP.get(event_type)
        if not mapping:
            return False
        key = mapping[0]
        return bool(self.config.get(f"notifications.events.{key}", False))

    def _log(self, channel: str, event: str, status: str, detail: str = "") -> None:
        try:
            self.db.insert("notifications_log", {
                "ts": time.time(), "channel": channel, "event": event,
                "status": status, "detail": detail[:500],
            })
        except Exception:  # pragma: no cover
            log.exception("could not record notification result")

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM notifications_log ORDER BY ts DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------
    def _fields(self, event: Event) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        data = event.data or {}
        if event.type == "server_started" and data.get("startup_seconds"):
            fields.append({"name": "Startup time", "value": f"{data['startup_seconds']:.1f} s", "inline": True})
        if event.type == "server_crashed":
            analysis = data.get("analysis") or {}
            fields.append({"name": "Exit code", "value": str(data.get("exit_code")), "inline": True})
            if analysis.get("category"):
                fields.append({
                    "name": f"{str(analysis.get('confidence', 'possible')).title()} cause",
                    "value": f"{analysis['category']}\n{analysis.get('summary', '')}"[:1000],
                    "inline": False,
                })
            if analysis.get("evidence"):
                evidence = "\n".join(analysis["evidence"][-3:])[:900]
                fields.append({"name": "Evidence", "value": f"```{evidence}```", "inline": False})
            if data.get("players_online"):
                fields.append({"name": "Players online at the time",
                               "value": ", ".join(data["players_online"])[:200], "inline": False})
            auto = self.config.get("monitor.auto_restart", True)
            fields.append({"name": "Automatic restart",
                           "value": "Enabled" if auto else "Disabled", "inline": True})
        if self.metrics and event.type in ("server_crashed", "high_ram", "high_cpu", "low_disk"):
            snap = self.metrics.last or {}
            if snap:
                fields.append({
                    "name": "Machine",
                    "value": (f"RAM {snap.get('ram_used_mb', 0)/1024:.1f} / "
                              f"{snap.get('ram_total_mb', 0)/1024:.1f} GB\n"
                              f"CPU {snap.get('cpu_percent', 0):.0f}%\n"
                              f"Disk {snap.get('disk_free_gb', 0):.1f} GB free"),
                    "inline": True,
                })
        for key in ("username", "value", "threshold", "name", "size_bytes"):
            if key in data and not any(f["name"].lower() == key for f in fields):
                value = data[key]
                if key == "size_bytes":
                    value = f"{float(value)/1024**3:.2f} GB"
                fields.append({"name": key.replace("_", " ").title(), "value": str(value)[:200],
                               "inline": True})
        return fields[:8]

    # ------------------------------------------------------------------
    async def send_discord(self, event: Event) -> bool:
        webhook = self.config.discord_webhook
        if not webhook:
            self._log("discord", event.type, "skipped", "No webhook URL is configured")
            return False
        emoji, colour, title = EVENT_MAP.get(event.type, ("", 0x5865F2, event.type))[1:]
        server_name = self.config.get("server.name", "Minecraft server")
        payload = {
            "username": "Minecraft Control",
            "embeds": [{
                "title": f"{emoji} {title}",
                "description": event.message[:2000] or title,
                "color": colour,
                "fields": self._fields(event),
                "footer": {"text": f"{server_name} · {time.strftime('%d %b %H:%M')}"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(event.ts)),
            }],
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
        cfg = self.config.get("notifications.email", {})
        emoji, _, title = EVENT_MAP.get(event.type, ("", 0, event.type))[1:]
        server_name = self.config.get("server.name", "Minecraft server")
        message = EmailMessage()
        message["Subject"] = f"[{server_name}] {emoji} {title}"
        message["From"] = cfg.get("from_address") or self.config.smtp_username
        message["To"] = ", ".join(cfg.get("to_addresses") or [])
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
        message.set_content("\n".join(str(l) for l in lines))

        if cfg.get("attach_crash_report") and data.get("crash_report"):
            self._attach(message, Path(data["crash_report"]))
        if cfg.get("attach_log_tail") and data.get("console_file"):
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
        cfg = self.config.get("notifications.email", {})
        host = cfg.get("host")
        port = int(cfg.get("port", 587))
        timeout = 25
        if cfg.get("use_ssl"):
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        try:
            server.ehlo()
            if cfg.get("use_tls") and not cfg.get("use_ssl"):
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
        cfg = self.config.get("notifications.email", {})
        if not cfg.get("host") or not cfg.get("to_addresses"):
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

    async def _report_failure(self, channel: str, detail: str) -> None:
        try:
            await self.bus.publish(Event(
                type="notification_failed", level="warn",
                message=f"{channel} notification could not be sent: {detail}"[:300],
                data={"channel": channel},
            ))
        except Exception:  # pragma: no cover
            log.exception("could not publish notification failure")

    # ------------------------------------------------------------------
    async def handle(self, event: Event) -> None:
        """Event bus subscriber. Never raises."""
        try:
            if event.type not in EVENT_MAP or not self.enabled_for(event.type):
                return
            min_interval = float(self.config.get("notifications.min_interval_seconds", 300))
            throttled = {"high_ram", "high_cpu", "low_disk", "low_tps", "high_mspt",
                         "auth_failure", "certificate_expiring"}
            if event.type in throttled:
                if time.time() - self._last_sent.get(event.type, 0) < min_interval:
                    return
            self._last_sent[event.type] = time.time()
            tasks = []
            if self.config.get("notifications.discord_enabled"):
                tasks.append(self.send_discord(event))
            if self.config.get("notifications.email_enabled"):
                tasks.append(self.send_email(event))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            log.exception("notification dispatch failed for %s", event.type)

    async def test(self, channel: str) -> dict[str, Any]:
        event = Event(type="server_started", level="success",
                      message="Test notification from Minecraft Server Control",
                      data={"startup_seconds": 0.0})
        if channel == "discord":
            ok = await self.send_discord(event)
        elif channel == "email":
            ok = await self.send_email(event)
        else:
            raise ValueError("Channel must be 'discord' or 'email'")
        return {"channel": channel, "sent": ok}
