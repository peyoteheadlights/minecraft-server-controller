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

from ..events import Event, EventBus
from ..security.paths import directory_size

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
        port = port or int(self.server.detected_port or self.config.get("server.port", 25565))
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            return False

    def tailscale_status(self) -> dict[str, Any]:
        """Report Tailscale state from an actual source.

        Source of truth, in order:
          1. `tailscale status --json` - the daemon's own view of whether it is
             connected. This is the only thing that proves connectivity.
          2. A network interface in the 100.64.0.0/10 range - proves an address
             is assigned, which is *not* the same as being connected. Reported
             as "interface detected", never as "connected".

        `connected` is True only when the daemon said so, False when it said
        otherwise, and None when we could not ask.
        """
        from ..security.certs import tailscale_status as cli_status

        report = cli_status()
        if report.get("cli_found") and report.get("connected") is not None and not report.get("error"):
            return {
                "connected": bool(report["connected"]),
                "verified": True,
                "source": "tailscale status --json",
                "address": (report.get("addresses") or [None])[0],
                "addresses": report.get("addresses") or [],
                "dns_name": report.get("dns_name"),
                "backend_state": report.get("backend_state"),
                "detail": ("Verified through the Tailscale daemon"
                           if report["connected"]
                           else f"Tailscale is installed but not connected "
                                f"({report.get('backend_state')})"),
            }

        # The CLI could not answer. Fall back to looking for an address, and be
        # explicit that this proves less.
        cli_problem = report.get("error") or "the tailscale command was not found"
        try:
            addrs = psutil.net_if_addrs()
        except Exception:  # pragma: no cover
            return {"connected": None, "verified": False, "source": "unavailable",
                    "address": None, "addresses": [],
                    "detail": f"Could not verify: {cli_problem}, and the network "
                              f"interfaces could not be read either."}
        for name, entries in addrs.items():
            for entry in entries:
                if entry.family != socket.AF_INET or not entry.address:
                    continue
                is_ts_name = "tailscale" in name.lower() or name.lower().startswith("ts")
                in_cgnat = False
                if entry.address.startswith("100."):
                    try:
                        in_cgnat = 64 <= int(entry.address.split(".")[1]) <= 127
                    except (ValueError, IndexError):
                        in_cgnat = False
                if is_ts_name or in_cgnat:
                    return {
                        "connected": None,
                        "verified": False,
                        "source": "network interface",
                        "address": entry.address,
                        "addresses": [entry.address],
                        "interface": name,
                        "detail": (f"A Tailscale-style address ({entry.address}) is assigned to "
                                   f"interface {name}, but connectivity could not be confirmed "
                                   f"because {cli_problem}."),
                    }
        return {
            "connected": None,
            "verified": False,
            "source": "network interface",
            "address": None,
            "addresses": [],
            "detail": f"No Tailscale address found on this machine, and {cli_problem}.",
        }

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
        th = self.config.get("thresholds", {})
        checks: list[dict[str, Any]] = []

        def add(name, ok, value, threshold=None, detail="", source="", unknown=False):
            checks.append({
                "name": name,
                "status": "unknown" if unknown else ("ok" if ok else "warn"),
                "value": value,
                "threshold": threshold,
                "detail": detail,
                "source": source,
            })

        state = self.server.state.value
        if state == "UNKNOWN":
            add("Minecraft process", False, "UNKNOWN", "ONLINE", unknown=True,
                detail="The agent has not yet verified whether Minecraft is running.",
                source="not checked")
        else:
            add("Minecraft process", state in ("ONLINE", "STARTING"), state, "ONLINE",
                detail=f"State is {state}", source=self.server._state_source())

        if self.server.tps is None:
            add("TPS", True, None, th.get("tps_min"), unknown=True,
                detail=self.server.tps_unavailable_reason() or "No tick-rate source available",
                source="no provider answered")
        else:
            add("TPS", self.server.tps >= float(th.get("tps_min", 18)), round(self.server.tps, 2),
                th.get("tps_min"), f"Minimum acceptable is {th.get('tps_min')}",
                source=self.server.tps_source or "server console reply")

        if self.server.mspt is None:
            add("MSPT", True, None, th.get("mspt_max"), unknown=True,
                detail="No tick-time report has been received from the server.",
                source="no provider answered")
        else:
            add("MSPT", self.server.mspt <= float(th.get("mspt_max", 50)), round(self.server.mspt, 1),
                th.get("mspt_max"), f"Maximum acceptable is {th.get('mspt_max')} ms",
                source=self.server.tps_source or "server console reply")

        if player_count is None:
            add("Players", True, None, None, unknown=True,
                detail="The player list has not been established yet. It becomes known when a "
                       "player joins or leaves, when /list is answered, or when the server stops.",
                source="not established")
        else:
            add("Players", True, player_count, self.config.get("server.max_players"),
                detail="Players currently connected", source="console join/leave and /list")

        add("CPU", snap["cpu_percent"] < float(th.get("cpu_percent", 90)),
            round(snap["cpu_percent"], 1), th.get("cpu_percent"),
            "Whole-machine CPU use, percent", source="psutil (operating system)")
        add("System RAM", snap["ram_percent"] < float(th.get("ram_percent", 90)),
            round(snap["ram_percent"], 1), th.get("ram_percent"),
            f"{snap['ram_used_mb']/1024:.1f} of {snap['ram_total_mb']/1024:.1f} GB used",
            source="psutil (operating system)")
        if snap["proc_ram_mb"] is None:
            add("Minecraft RAM", True, None, None, unknown=True,
                detail="The Minecraft process is not running, or its memory could not be read. "
                       "The -Xmx value is an allocation limit, not a measurement, so it is not "
                       "shown here.",
                source="not measured")
        else:
            add("Minecraft RAM", True, round(snap["proc_ram_mb"] / 1024, 2), None,
                f"Actual process memory. Allocation limit is "
                f"{' '.join(str(a) for a in self.config.get('server.jvm_args', [])) or 'not set'}",
                source="psutil process RSS")
        if snap["disk_free_gb"] is None:
            add("Disk space", True, None, th.get("disk_free_gb"), unknown=True,
                detail=snap["disk_unknown_reason"], source="filesystem query failed")
        else:
            add("Disk space", snap["disk_free_gb"] > float(th.get("disk_free_gb", 20)),
                round(snap["disk_free_gb"], 1), th.get("disk_free_gb"),
                "Free space on the server drive, GB", source="filesystem query")

        tailscale = self.tailscale_status()
        if tailscale["connected"] is None:
            add("Tailscale", True, None, None, unknown=True,
                detail=tailscale["detail"], source=tailscale["source"])
        else:
            add("Tailscale", tailscale["connected"],
                tailscale.get("dns_name") or tailscale.get("address") or "connected",
                None, tailscale["detail"], source=tailscale["source"])

        port = int(self.server.detected_port or self.config.get("server.port", 25565))
        if state != "ONLINE":
            add(f"Port {port}", True, None, "listening", unknown=True,
                detail="Not checked: the server is not online, so the port is not expected to "
                       "be listening.",
                source="not checked")
        else:
            listening = self.port_listening(port)
            add(f"Port {port}", listening, "listening" if listening else "not listening",
                "listening", "Minecraft accepts connections when the server is online",
                source="TCP connect attempt")

        if self.config.tls_enabled:
            cert = self.certificate_status()
            if not cert.get("parsed"):
                add("TLS certificate", False, "not readable", None,
                    cert.get("parse_error") or "The certificate file could not be read",
                    source="certificate file")
            else:
                days = cert.get("days_remaining")
                severity = cert.get("expiry_severity")
                add("TLS certificate", severity == "ok",
                    f"{days:.0f} days remaining" if days is not None else None,
                    self.config.get("tls.expiry_warn_days"),
                    f"Issued by {cert.get('issuer')}",
                    source="certificate file", unknown=days is None)

        recent = self.server.recent_crash_count()
        window = self.config.get("monitor.crash_window_minutes", 10)
        add("Recent crashes", recent == 0, recent, 0,
            f"Crashes in the last {window} minutes", source="agent crash records")

        unknown = [c["name"] for c in checks if c["status"] == "unknown"]
        warnings = [c["name"] for c in checks if c["status"] == "warn"]
        if warnings:
            overall = "ATTENTION NEEDED"
        elif unknown:
            overall = "PARTIALLY VERIFIED"
        else:
            overall = "ALL CHECKS VERIFIED"

        return {
            "overall": overall,
            "verified_count": len([c for c in checks if c["status"] != "unknown"]),
            "unverified": unknown,
            "warnings": warnings,
            "note": ("Some values could not be measured and are reported as unknown. "
                     "They are not counted as passing.") if unknown else "",
            "checks": checks,
            "metrics": snap,
            "players": player_count,
            "state": state,
            "generated_at": time.time(),
        }

    # ------------------------------------------------------------------
    async def _check_thresholds(self, sample: dict[str, Any]) -> None:
        th = self.config.get("thresholds", {})
        min_interval = float(self.config.get("notifications.min_interval_seconds", 300))
        now = time.time()

        async def alert(key: str, type_: str, message: str, data: dict) -> None:
            if now - self._alert_sent.get(key, 0) < min_interval:
                return
            self._alert_sent[key] = now
            await self.bus.publish(Event(type=type_, message=message, level="warn", data=data))

        if sample["cpu_percent"] >= float(th.get("cpu_percent", 90)):
            await alert("cpu", "high_cpu",
                        f"CPU at {sample['cpu_percent']:.0f}% (threshold {th.get('cpu_percent')}%)",
                        {"value": sample["cpu_percent"], "threshold": th.get("cpu_percent")})
        if sample["ram_percent"] >= float(th.get("ram_percent", 90)):
            await alert("ram", "high_ram",
                        f"RAM at {sample['ram_percent']:.0f}% "
                        f"({sample['ram_used_mb']/1024:.1f} of {sample['ram_total_mb']/1024:.1f} GB)",
                        {"value": sample["ram_percent"], "threshold": th.get("ram_percent")})
        if (sample["disk_free_gb"] is not None
                and sample["disk_free_gb"] <= float(th.get("disk_free_gb", 20))):
            await alert("disk", "low_disk",
                        f"Only {sample['disk_free_gb']:.1f} GB free "
                        f"(threshold {th.get('disk_free_gb')} GB)",
                        {"value": sample["disk_free_gb"], "threshold": th.get("disk_free_gb")})
        if sample["tps"] is not None and sample["tps"] < float(th.get("tps_min", 18)):
            await alert("tps", "low_tps",
                        f"TPS at {sample['tps']:.1f} (threshold {th.get('tps_min')})",
                        {"value": sample["tps"], "threshold": th.get("tps_min")})
        if sample["mspt"] is not None and sample["mspt"] > float(th.get("mspt_max", 50)):
            await alert("mspt", "high_mspt",
                        f"MSPT at {sample['mspt']:.0f} ms (threshold {th.get('mspt_max')} ms)",
                        {"value": sample["mspt"], "threshold": th.get("mspt_max")})

    async def sample_once(self, player_count: int | None = None) -> dict[str, Any]:
        sample = self.snapshot()
        sample["players"] = player_count
        try:
            self.db.insert("metrics", {
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
            })
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
        interval = float(self.config.get("monitor.sample_interval", 10))
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
