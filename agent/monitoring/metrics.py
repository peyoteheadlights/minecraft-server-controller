"""Performance monitoring and health checks.

Every number reported here is measured. Where a value cannot be measured -
TPS on a server with no tick-reporting command, for example - it is reported
as null with a reason, not guessed.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import time
from typing import Any

import psutil

from .. import tailscale
from ..events import Event, EventBus
from ..security.paths import directory_size
from . import health

log = logging.getLogger("msc.metrics")


class MetricsMonitor:
    def __init__(self, config, bus: EventBus, db, server):
        self.config = config
        self.bus = bus
        self.db = db
        self.server = server
        self.last: dict[str, Any] = {}
        self._task: asyncio.Task | None = None
        self._alert_sent: dict[str, float] = {}
        self._net_baseline = self._net_counters()
        self._net_baseline_ts = time.time()
        self._storage_cache: tuple[float, dict] | None = None
        self._storage_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    @staticmethod
    def _net_counters() -> tuple[float, float]:
        try:
            io = psutil.net_io_counters()
            return io.bytes_sent, io.bytes_recv
        except Exception:  # pragma: no cover
            return 0.0, 0.0

    def _process(self) -> psutil.Process | None:
        pid = self.server.pid
        if not pid:
            return None
        try:
            return psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def snapshot(self, include_process: bool = True) -> dict[str, Any]:
        now = time.time()
        vm = psutil.virtual_memory()
        disk, disk_reason = self._server_disk_usage()
        sent, recv = self._net_counters()
        elapsed = max(now - self._net_baseline_ts, 0.001)
        net_sent_mb = (sent - self._net_baseline[0]) / 1024**2 / elapsed
        net_recv_mb = (recv - self._net_baseline[1]) / 1024**2 / elapsed
        self._net_baseline, self._net_baseline_ts = (sent, recv), now

        proc_ram = None
        proc_cpu = None
        if include_process:
            proc = self._process()
            if proc:
                try:
                    proc_ram = proc.memory_info().rss / 1024**2
                    proc_cpu = proc.cpu_percent(interval=None) / max(psutil.cpu_count() or 1, 1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        data = {
            "ts": now,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "process_cpu_percent": proc_cpu,
            "ram_used_mb": (vm.total - vm.available) / 1024**2,
            "ram_total_mb": vm.total / 1024**2,
            "ram_percent": vm.percent,
            "proc_ram_mb": proc_ram,
            "disk_free_gb": disk.free / 1024**3 if disk else None,
            "disk_total_gb": disk.total / 1024**3 if disk else None,
            "disk_percent": (disk.used / disk.total * 100) if disk and disk.total else None,
            "disk_unknown_reason": disk_reason,
            "net_sent_mb_s": max(net_sent_mb, 0.0),
            "net_recv_mb_s": max(net_recv_mb, 0.0),
            "tps": self.server.tps,
            "mspt": self.server.mspt,
            "tps_updated": self.server.tps_updated,
            "players": None,
        }
        self.last = data
        return data

    def _server_disk_usage(self) -> tuple[Any, str | None]:
        """Usage of the drive holding the server folder, or (None, reason).

        Never falls back to another drive: that drive's free space is not the
        server's free space.
        """
        try:
            return shutil.disk_usage(self.config.server_dir), None
        except OSError as exc:
            return None, f"The server folder's drive could not be read: {exc}"

    # ------------------------------------------------------------------
    async def storage(self, max_age: float = 120.0) -> dict[str, Any]:
        """Disk usage by category, measured in a worker thread and cached.

        Walking a 40 GB world takes seconds, so it never runs on the event
        loop, and concurrent callers share one walk.
        """
        if self._storage_cache and time.time() - self._storage_cache[0] < max_age:
            return self._storage_cache[1]
        async with self._storage_lock:
            if self._storage_cache and time.time() - self._storage_cache[0] < max_age:
                return self._storage_cache[1]
            result = await asyncio.to_thread(self.storage_breakdown)
            self._storage_cache = (time.time(), result)
            return result

    def storage_breakdown(self) -> dict[str, Any]:
        """Measure disk usage by category (blocking; use storage() from async code).

        The agent's data folder (backups, mod backups, the database) is
        counted under Backups only, never again under Other, even when it
        lives inside the server folder.
        """
        base = self.config.server_dir
        worlds = 0
        for name in ("world", "world_nether", "world_the_end"):
            worlds += directory_size(base / name)
        logs = directory_size(base / "logs")
        mods = directory_size(self.config.mods_dir)
        backups = directory_size(self.config.backup_dir)
        mod_backups = directory_size(self.config.mod_backup_dir)
        excluded = [self.config.data_dir, self.config.backup_dir, self.config.mod_backup_dir]
        total_dir = directory_size(base, exclude=excluded)
        other = max(total_dir - worlds - logs - mods, 0)
        disk, disk_reason = self._server_disk_usage()
        return {
            "worlds_gb": worlds / 1024**3,
            "backups_gb": (backups + mod_backups) / 1024**3,
            "logs_gb": logs / 1024**3,
            "mods_gb": mods / 1024**3,
            "other_gb": other / 1024**3,
            "free_gb": disk.free / 1024**3 if disk else None,
            "free_unknown_reason": disk_reason,
            "measured_at": time.time(),
        }

    # ------------------------------------------------------------------
    def port_listening(self, port: int | None = None, host: str = "127.0.0.1") -> bool:
        port = port or int(self.server.detected_port or self.config.server.port)
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            return False

    def tailscale_status(self) -> dict[str, Any]:
        return tailscale.connection_status()

    def certificate_status(self) -> dict[str, Any]:
        """TLS certificate facts, read from the files on disk."""
        from ..security.tls import inspect_certificate

        if not self.config.tls_enabled:
            return {"enabled": False, "detail": "TLS is disabled in configuration"}
        info = inspect_certificate(self.config.tls_certificate, self.config.tls_private_key)
        data = info.to_dict()
        data["enabled"] = True
        data["hostname"] = self.config.dashboard_hostname or None
        data["covers_hostname"] = info.covers(self.config.dashboard_hostname)
        return data

    def health(self, player_count: int | None = None) -> dict[str, Any]:
        """Explicit checks, each with its value, its threshold and its source.

        There is no single green "HEALTHY" light. When something could not be
        measured the overall status is PARTIALLY VERIFIED and the unverified
        items are listed, because a health summary built out of missing data is
        worse than no summary at all.
        """
        snap = self.snapshot()
        th = self.config.thresholds
        state = self.server.state.value
        port = int(self.server.detected_port or self.config.server.port)
        checks = [
            health.process(self.server),
            health.tps(self.server, th),
            health.mspt(self.server, th),
            health.players(player_count, self.config.server.max_players),
            health.cpu(snap, th),
            health.system_ram(snap, th),
            health.minecraft_ram(snap, self.config.server.jvm_args),
            health.disk(snap, th),
            health.tailscale(self.tailscale_status()),
            health.port(port, state, self.port_listening(port) if state == "ONLINE" else None),
        ]
        if self.config.tls_enabled:
            checks.append(
                health.certificate(self.certificate_status(), self.config.tls.expiry_warn_days)
            )
        checks.append(
            health.recent_crashes(
                self.server.recent_crash_count(), self.config.monitor.crash_window_minutes
            )
        )
        return {
            **health.summarize(checks),
            "checks": checks,
            "metrics": snap,
            "players": player_count,
            "state": state,
            "generated_at": time.time(),
        }

    # ------------------------------------------------------------------
    async def _check_thresholds(self, sample: dict[str, Any]) -> None:
        th = self.config.thresholds
        min_interval = self.config.notifications.min_interval_seconds
        now = time.time()

        async def alert(key: str, type_: str, message: str, data: dict) -> None:
            if now - self._alert_sent.get(key, 0) < min_interval:
                return
            self._alert_sent[key] = now
            await self.bus.publish(Event(type=type_, message=message, level="warn", data=data))

        if sample["cpu_percent"] >= th.cpu_percent:
            await alert(
                "cpu",
                "high_cpu",
                f"CPU at {sample['cpu_percent']:.0f}% (threshold {th.cpu_percent}%)",
                {"value": sample["cpu_percent"], "threshold": th.cpu_percent},
            )
        if sample["ram_percent"] >= th.ram_percent:
            await alert(
                "ram",
                "high_ram",
                f"RAM at {sample['ram_percent']:.0f}% "
                f"({sample['ram_used_mb'] / 1024:.1f} of {sample['ram_total_mb'] / 1024:.1f} GB)",
                {"value": sample["ram_percent"], "threshold": th.ram_percent},
            )
        if sample["disk_free_gb"] is not None and sample["disk_free_gb"] <= th.disk_free_gb:
            await alert(
                "disk",
                "low_disk",
                f"Only {sample['disk_free_gb']:.1f} GB free (threshold {th.disk_free_gb} GB)",
                {"value": sample["disk_free_gb"], "threshold": th.disk_free_gb},
            )
        if sample["tps"] is not None and sample["tps"] < th.tps_min:
            await alert(
                "tps",
                "low_tps",
                f"TPS at {sample['tps']:.1f} (threshold {th.tps_min})",
                {"value": sample["tps"], "threshold": th.tps_min},
            )
        if sample["mspt"] is not None and sample["mspt"] > th.mspt_max:
            await alert(
                "mspt",
                "high_mspt",
                f"MSPT at {sample['mspt']:.0f} ms (threshold {th.mspt_max} ms)",
                {"value": sample["mspt"], "threshold": th.mspt_max},
            )

    async def sample_once(self, player_count: int | None = None) -> dict[str, Any]:
        sample = self.snapshot()
        sample["players"] = player_count
        try:
            self.db.insert(
                "metrics",
                {
                    "server_id": self.server.server_id,
                    "ts": sample["ts"],
                    "cpu_percent": sample["cpu_percent"],
                    "ram_used_mb": sample["ram_used_mb"],
                    "ram_total_mb": sample["ram_total_mb"],
                    "proc_ram_mb": sample["proc_ram_mb"],
                    "disk_free_gb": sample["disk_free_gb"],
                    "disk_percent": sample["disk_percent"],
                    "net_sent_mb": sample["net_sent_mb_s"],
                    "net_recv_mb": sample["net_recv_mb_s"],
                    "tps": sample["tps"],
                    "mspt": sample["mspt"],
                    "players": player_count,
                },
            )
        except Exception:  # pragma: no cover
            log.exception("could not store metrics sample")
        await self._check_thresholds(sample)
        await self.bus.publish(Event(type="metrics", message="", data=sample))
        return sample

    def history(self, hours: float = 6, limit: int = 720) -> list[dict[str, Any]]:
        cutoff = time.time() - hours * 3600
        return self.db.query(
            "SELECT * FROM metrics WHERE server_id = ? AND ts >= ? ORDER BY ts ASC LIMIT ?",
            (self.server.server_id, cutoff, limit),
        )

    # ------------------------------------------------------------------
    async def run(self, player_source=None) -> None:
        interval = self.config.monitor.sample_interval
        psutil.cpu_percent(interval=None)  # prime the counter
        while True:
            try:
                count = None
                if player_source:
                    count = len(player_source())
                await self.sample_once(player_count=count)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                log.exception("metrics loop error")
            await asyncio.sleep(interval)

    def start(self, player_source=None) -> None:
        if not self._task:
            self._task = asyncio.create_task(self.run(player_source), name="metrics")

    async def stop(self) -> None:
        for task in (self._task,):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = None
