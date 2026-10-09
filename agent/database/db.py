"""SQLite storage with a tiny forward-only migration runner.

Raw Minecraft logs stay on disk as files; only metadata, pointers and small
structured rows live here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..events import AGENT_SCOPE

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
    (
        3,
        # Several servers. Settings rows written by one server's managers
        # are now keyed "server:<id>:<key>"; an install with exactly one
        # registered server gets its existing rows copied to that form (the
        # originals are left as they were). Audit entries can name the server
        # they were about. Jobs are long operations the dashboard follows.
        """
        INSERT OR IGNORE INTO settings (key, value, updated_at)
        SELECT 'server:' || s.id || ':' || st.key, st.value, st.updated_at
        FROM settings st, servers s
        WHERE (SELECT COUNT(*) FROM servers) = 1 AND st.key NOT LIKE 'server:%';
        ALTER TABLE audit_log ADD COLUMN server_id TEXT;
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            server_id TEXT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            risky INTEGER NOT NULL DEFAULT 0,
            done REAL,
            total REAL,
            unit TEXT,
            step TEXT,
            message TEXT,
            result TEXT,
            user TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            finished_at REAL
        );
        CREATE INDEX idx_jobs_created ON jobs(created_at DESC);
        """,
    ),
    (
        4,
        # Each server's color, so it follows the server to every device.
        # Empty until the agent assigns the next unused palette color.
        """
        ALTER TABLE servers ADD COLUMN color TEXT;
        """,
    ),
    (
        5,
        # Server types. Every server registered before them is Fabric. The
        # loader column records the loader version this app installed
        # (empty when the app did not install it); what is actually running
        # is only ever read from the console.
        """
        ALTER TABLE servers ADD COLUMN type TEXT NOT NULL DEFAULT 'fabric';
        ALTER TABLE servers ADD COLUMN loader TEXT;
        """,
    ),
    (
        6,
        # Which edition a player joined from. Empty for everyone seen before
        # crossplay existed: that is Unknown, not Java.
        """
        ALTER TABLE players ADD COLUMN edition TEXT;
        """,
    ),
    (
        7,
        # Phone alerts: one row per browser that subscribed to Web Push.
        # The endpoint is the push service's own address for that browser,
        # and the two keys are the ones it handed over to be written to.
        """
        CREATE TABLE push_subscriptions (
            endpoint TEXT PRIMARY KEY,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user TEXT,
            label TEXT,
            created_at REAL NOT NULL,
            last_sent REAL,
            last_result TEXT
        );
        """,
    ),
    (
        8,
        # Helper accounts: friends' own logins with limited access. The
        # password is hashed exactly like the owner's; servers is a JSON list
        # of the server ids the helper may use, empty for every server.
        # Each backup can also have a second copy off the PC (another drive
        # or a synced cloud folder), with that copy's own checked status.
        """
        CREATE TABLE accounts (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'helper',
            servers TEXT,
            created_at REAL NOT NULL,
            created_by TEXT,
            password_changed_at REAL
        );
        ALTER TABLE backups ADD COLUMN copy_path TEXT;
        ALTER TABLE backups ADD COLUMN copy_status TEXT;
        ALTER TABLE backups ADD COLUMN copy_detail TEXT;
        ALTER TABLE backups ADD COLUMN copy_checked_at REAL;
        """,
    ),
    (
        9,
        # "Keep me signed in on this device": a longer sign-in that each use
        # renews, listed with the others on the Security page.
        """
        ALTER TABLE sessions ADD COLUMN remember INTEGER NOT NULL DEFAULT 0;
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
        return int(cur.lastrowid or 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- helpers ----------------------------------------------------------
    def register_server(
        self, server_id: str, name: str, directory: str, type_: str = "fabric"
    ) -> None:
        self.execute(
            "INSERT INTO servers (id, name, directory, created_at, type) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, directory=excluded.directory, "
            "type=excluded.type",
            (server_id, name, directory, time.time(), type_),
        )

    def set_server_software(self, server_id: str, type_: str, loader: str | None) -> None:
        """Record the type and the loader version this app installed."""
        self.execute(
            "UPDATE servers SET type = ?, loader = ? WHERE id = ?", (type_, loader, server_id)
        )

    def server_row(self, server_id: str) -> dict | None:
        return self.query_one("SELECT * FROM servers WHERE id = ?", (server_id,))

    def server_color(self, server_id: str) -> str | None:
        row = self.query_one("SELECT color FROM servers WHERE id = ?", (server_id,))
        return row["color"] if row else None

    def set_server_color(self, server_id: str, color: str) -> None:
        self.execute("UPDATE servers SET color = ? WHERE id = ?", (color, server_id))

    def add_event(
        self,
        server_id: str,
        type_: str,
        message: str,
        level: str = "info",
        data: dict | None = None,
    ) -> int:
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

    def add_events(self, rows: list[dict[str, Any]]) -> None:
        """Insert many event rows in one transaction."""
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO events (server_id, ts, type, level, message, data) "
                "VALUES (:server_id, :ts, :type, :level, :message, :data)",
                rows,
            )
            self._conn.commit()

    def recent_events(self, server_id: str, limit: int = 100) -> list[dict]:
        """One server's events, plus the agent-wide ones (sign-ins, the
        agent starting), which belong on every server's history."""
        return self.query(
            "SELECT * FROM events WHERE server_id IN (?, ?) ORDER BY ts DESC LIMIT ?",
            (server_id, AGENT_SCOPE, limit),
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
        server_id: str | None = None,
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
                "server_id": server_id,
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


class ServerDb:
    """One server's handle on the shared database.

    Settings rows are kept apart per server ("server:<id>:<key>"), and audit
    entries record the server. Everything else is the shared Database; the
    queries themselves already filter on server_id.
    """

    def __init__(self, db: Database, server_id: str):
        self.db = db
        self.server_id = server_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self.db, name)

    def _key(self, key: str) -> str:
        return f"server:{self.server_id}:{key}"

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.db.get_setting(self._key(key), default)

    def set_setting(self, key: str, value: Any) -> None:
        self.db.set_setting(self._key(key), value)

    def audit(self, action: str, **kwargs: Any) -> int:
        kwargs.setdefault("server_id", self.server_id)
        return self.db.audit(action, **kwargs)
