"""Crash evidence collection.

When Minecraft dies unexpectedly the agent snapshots everything that would
otherwise be gone by the time a human looks: console tail, error lines, the
newest crash report, a copy of latest.log, machine metrics, who was online,
and which mods were loaded.

Raw logs are written to files under the server's crashes/<id>/ folder in the
agent data folder; SQLite only
holds the metadata and the paths.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from .analyzer import analyze
from .state import ExitReason

log = logging.getLogger("msc.crash")

CONSOLE_LINES = 200


class CrashReporter:
    def __init__(self, config, db, server, metrics=None, players=None, mods=None):
        self.config = config
        self.db = db
        self.server = server
        self.metrics = metrics
        self.players = players
        self.mods = mods
        self.crash_dir = config.crash_dir
        self.crash_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def _latest_crash_report(self, since: float) -> Path | None:
        folder = self.config.server_dir / "crash-reports"
        if not folder.is_dir():
            return None
        candidates = [p for p in folder.glob("crash-*.txt") if p.is_file()]
        if not candidates:
            return None
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        # only claim it belongs to this crash if it is recent
        if newest.stat().st_mtime < since - 120:
            return None
        return newest

    def _latest_log(self) -> Path | None:
        candidate = self.config.server_dir / "logs" / "latest.log"
        return candidate if candidate.is_file() else None

    def _known_mod_ids(self) -> list[str]:
        if not self.mods:
            return []
        try:
            return [m["mod_id"] for m in self.mods.list_installed() if m.get("mod_id")]
        except Exception:  # pragma: no cover - mod scan must never block a crash report
            log.exception("could not list mods for crash analysis")
            return []

    # ------------------------------------------------------------------
    async def collect(self, exit_code: int, reason: ExitReason) -> dict[str, Any]:
        ts = time.time()
        crash_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts))
        folder = self.crash_dir / crash_id
        folder.mkdir(parents=True, exist_ok=True)

        console_lines = [ln.raw for ln in self.server.console.tail(CONSOLE_LINES)]
        error_lines = [ln.raw for ln in self.server.console.by_level("ERROR", limit=60)]
        warn_lines = [ln.raw for ln in self.server.console.by_level("WARN", limit=30)]

        console_path = folder / "console-tail.log"
        console_path.write_text("\n".join(console_lines), encoding="utf-8", errors="replace")

        report_path = None
        source_report = self._latest_crash_report(ts)
        if source_report:
            report_path = folder / source_report.name
            try:
                shutil.copy2(source_report, report_path)
            except OSError:
                log.exception("could not copy crash report")
                report_path = source_report

        log_copy = None
        source_log = self._latest_log()
        if source_log:
            log_copy = folder / "latest.log"
            try:
                # keep only the tail; a modded latest.log can be enormous
                text = source_log.read_text(encoding="utf-8", errors="replace")
                log_copy.write_text("\n".join(text.splitlines()[-2000:]), encoding="utf-8")
            except OSError:
                log.exception("could not copy latest.log")
                log_copy = None

        analysis_lines = list(console_lines)
        if report_path and Path(report_path).is_file():
            try:
                analysis_lines += (
                    Path(report_path)
                    .read_text(encoding="utf-8", errors="replace")
                    .splitlines()[:400]
                )
            except OSError:
                pass

        analysis = analyze(analysis_lines, exit_code=exit_code, known_mod_ids=self._known_mod_ids())

        snapshot: dict[str, Any] = {}
        if self.metrics:
            try:
                snapshot = self.metrics.snapshot(include_process=False)
            except Exception:  # pragma: no cover
                log.exception("metrics snapshot failed during crash collection")
        online_players = []
        if self.players:
            try:
                online_players = [p["username"] for p in self.players.online()]
            except Exception:  # pragma: no cover
                log.exception("player snapshot failed during crash collection")

        context = {
            "crash_id": crash_id,
            "ts": ts,
            "exit_code": exit_code,
            "reason": reason.value,
            "analysis": analysis.to_dict(),
            "console_tail": console_lines[-40:],
            "error_lines": error_lines[-15:],
            "warn_lines": warn_lines[-10:],
            "crash_report": str(report_path) if report_path else None,
            "log_file": str(log_copy) if log_copy else None,
            "console_file": str(console_path),
            "players_online": online_players,
            "minecraft_version": self.server.mc_version,
            "fabric_loader": self.server.loader_version,
            "java_version": self.server.java_version,
            "mod_count": self.server.mod_count,
            "metrics": snapshot,
        }
        (folder / "context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")

        try:
            crash_row = self.db.insert(
                "crashes",
                {
                    "server_id": self.server.server_id,
                    "ts": ts,
                    "exit_code": exit_code,
                    "category": analysis.category,
                    "confidence": analysis.confidence,
                    "summary": analysis.summary,
                    "evidence": json.dumps(analysis.evidence),
                    "report_path": str(report_path) if report_path else None,
                    "log_path": str(log_copy) if log_copy else str(console_path),
                    "context": json.dumps(
                        {k: v for k, v in context.items() if k not in ("console_tail",)}
                    ),
                    "restarted": 0,
                },
            )
            context["id"] = crash_row
            self.db.add_event(
                self.server.server_id,
                "server_crashed",
                f"Crash: {analysis.category} ({analysis.confidence})",
                level="error",
                data={"crash_id": crash_row, "category": analysis.category},
            )
        except Exception:  # pragma: no cover
            log.exception("could not store crash record")
        return context

    # ------------------------------------------------------------------
    def list_crashes(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM crashes WHERE server_id = ? ORDER BY ts DESC LIMIT ?",
            (self.server.server_id, limit),
        )
        for row in rows:
            row["evidence"] = json.loads(row.get("evidence") or "[]")
            row["context"] = json.loads(row.get("context") or "{}")
        return rows

    def get_crash(self, crash_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM crashes WHERE id = ?", (crash_id,))
        if not row:
            return None
        row["evidence"] = json.loads(row.get("evidence") or "[]")
        row["context"] = json.loads(row.get("context") or "{}")
        path = row.get("log_path")
        if path and Path(path).is_file():
            try:
                row["log_tail"] = (
                    Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
                )
            except OSError:
                row["log_tail"] = []
        return row

    def mark_restarted(self, crash_db_id: int) -> None:
        self.db.execute("UPDATE crashes SET restarted = 1 WHERE id = ?", (crash_db_id,))
