"""SQLite storage with a tiny forward-only migration runner.

Raw Minecraft logs stay on disk as files; only metadata, pointers and small
structured rows live here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            directory TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            ts REAL NOT NULL,
            type TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            data TEXT
        );
        CREATE INDEX idx_events_ts ON events(server_id, ts DESC);
        CREATE TABLE players (
            server_id TEXT NOT NULL,
            username TEXT NOT NULL,
            uuid TEXT,
            first_seen REAL,
            last_seen REAL,
            total_seconds REAL NOT NULL DEFAULT 0,
            sessions INTEGER NOT NULL DEFAULT 0,
            online INTEGER NOT NULL DEFAULT 0,
            session_started REAL,
            PRIMARY KEY (server_id, username)
        );
        CREATE TABLE player_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            username TEXT NOT NULL,
            uuid TEXT,
            joined_at REAL NOT NULL,
            left_at REAL
        );
        CREATE TABLE metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            ts REAL NOT NULL,
            cpu_percent REAL,
            ram_used_mb REAL,
            ram_total_mb REAL,
            proc_ram_mb REAL,
            disk_free_gb REAL,
            disk_percent REAL,
            net_sent_mb REAL,
            net_recv_mb REAL,
            tps REAL,
            mspt REAL,
            players INTEGER
        );
        CREATE INDEX idx_metrics_ts ON metrics(server_id, ts DESC);
        CREATE TABLE crashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            ts REAL NOT NULL,
            exit_code INTEGER,
            category TEXT,
            confidence TEXT,
            summary TEXT,
            evidence TEXT,
            report_path TEXT,
            log_path TEXT,
            context TEXT,
            restarted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'manual',
            created_at REAL NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            includes TEXT,
            sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'ok',
            note TEXT
        );
        CREATE TABLE mod_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            ts REAL NOT NULL,
            user TEXT,
            action TEXT NOT NULL,
            mod_id TEXT,
            mod_name TEXT,
            old_version TEXT,
            new_version TEXT,
            source TEXT,
            sha256 TEXT,
            result TEXT NOT NULL DEFAULT 'ok',
            detail TEXT
        );
        CREATE TABLE mod_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            mod_id TEXT NOT NULL,
            version TEXT NOT NULL,
            filename TEXT NOT NULL,
            archive_path TEXT NOT NULL,
            sha256 TEXT,
            source TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            name TEXT NOT NULL,
            task TEXT NOT NULL,
            kind TEXT NOT NULL,
            expr TEXT NOT NULL,
            payload TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run REAL,
            next_run REAL,
            last_result TEXT
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            user TEXT,
            source_ip TEXT,
            action TEXT NOT NULL,
            target TEXT,
            result TEXT NOT NULL DEFAULT 'ok',
            detail TEXT
        );
        CREATE TABLE notifications_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            channel TEXT NOT NULL,
            event TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT
        );
        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            last_used REAL,
            source_ip TEXT,
            label TEXT
        );
        CREATE TABLE login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            user TEXT,
            source_ip TEXT,
            success INTEGER NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        """,
    ),
]


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    # -- core -------------------------------------------------------------
    def migrate(self) -> int:
        """Apply pending migrations, each in its own transaction.

        A migration and its schema_version row commit together or not at
        all, so a failure never leaves a half-applied schema behind.
        """
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            self._conn.commit()
            row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, script in MIGRATIONS:
                if version <= current:
                    continue
                # executescript commits anything pending and then runs the
                # script as-is, so the transaction is opened and closed
                # inside the script itself.
                try:
                    self._conn.executescript(
                        "BEGIN;\n"
                        f"{script}\n;"
                        "INSERT INTO schema_version (version, applied_at) "
                        f"VALUES ({int(version)}, {time.time()!r});\n"
                        "COMMIT;"
                    )
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
                current = version
            return current

    @property
    def version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] or 0

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, values: dict[str, Any]) -> int:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))
        return int(cur.lastrowid)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- helpers ----------------------------------------------------------
    def register_server(self, server_id: str, name: str, directory: str) -> None:
        self.execute(
            "INSERT INTO servers (id, name, directory, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, directory=excluded.directory",
            (server_id, name, directory, time.time()),
        )

    def add_event(self, server_id: str, type_: str, message: str, level: str = "info", data: dict | None = None) -> int:
        return self.insert(
            "events",
            {
                "server_id": server_id,
                "ts": time.time(),
                "type": type_,
                "level": level,
                "message": message,
                "data": json.dumps(data) if data else None,
            },
        )

    def recent_events(self, server_id: str, limit: int = 100) -> list[dict]:
        return self.query(
            "SELECT * FROM events WHERE server_id = ? ORDER BY ts DESC LIMIT ?",
            (server_id, limit),
        )

    def list_servers(self) -> list[dict]:
        return self.query("SELECT * FROM servers")

    def audit_entries(self, limit: int = 100) -> list[dict]:
        return self.query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))

    def audit(
        self,
        action: str,
        user: str | None = None,
        target: str | None = None,
        result: str = "ok",
        detail: str | None = None,
        source_ip: str | None = None,
    ) -> int:
        return self.insert(
            "audit_log",
            {
                "ts": time.time(),
                "user": user,
                "source_ip": source_ip,
                "action": action,
                "target": target,
                "result": result,
                "detail": detail,
            },
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )

    def prune(self, metrics_days: int = 14, events_keep: int = 5000) -> None:
        cutoff = time.time() - metrics_days * 86400
        self.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        self.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (events_keep,),
        )
        self.execute("DELETE FROM login_attempts WHERE ts < ?", (time.time() - 30 * 86400,))
