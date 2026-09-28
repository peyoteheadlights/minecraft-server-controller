"""Player presence and playtime tracking.

Only a username, the Mojang UUID printed by the server, and timestamps are
stored. IP addresses are deliberately not captured: the server prints them on
connect, and this tracker drops them.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..events import Event, EventBus

log = logging.getLogger("msc.players")


class PlayerTracker:
    def __init__(self, config, bus: EventBus, db, server_id: str = "main"):
        self.config = config
        self.bus = bus
        self.db = db
        self.server_id = server_id
        self._pending_uuid: dict[str, str] = {}
        # The online list is only trustworthy once we have a source for it:
        # either a /list reply, an observed join/leave, or an observed server
        # stop. Until then the count is UNKNOWN, not zero.
        self.verified_at: float | None = None
        self.verified_source: str | None = None

    # ------------------------------------------------------------------
    async def handle_signals(self, sig, line) -> None:
        """Hook called by MinecraftServer for every console line."""
        if sig.player_uuid:
            name, uuid = sig.player_uuid
            self._pending_uuid[name] = uuid
        if sig.player_joined:
            await self.player_joined(sig.player_joined)
        if sig.player_left:
            await self.player_left(sig.player_left)
        if sig.player_list:
            online, _max, names = sig.player_list
            await self.reconcile(names)

    # ------------------------------------------------------------------
    def mark_verified(self, source: str) -> None:
        self.verified_at = time.time()
        self.verified_source = source

    @property
    def verified(self) -> bool:
        return self.verified_at is not None

    def online_count(self) -> int | None:
        """Player count, or None when it has not been established."""
        return len(self.online()) if self.verified else None

    async def player_joined(self, username: str) -> None:
        now = time.time()
        self.mark_verified("join observed in console")
        uuid = self._pending_uuid.pop(username, None)
        row = self.db.query_one(
            "SELECT * FROM players WHERE server_id = ? AND username = ?", (self.server_id, username)
        )
        if row:
            self.db.execute(
                "UPDATE players SET online = 1, session_started = ?, last_seen = ?, "
                "sessions = sessions + 1, uuid = COALESCE(?, uuid) WHERE server_id = ? AND username = ?",
                (now, now, uuid, self.server_id, username),
            )
        else:
            self.db.insert("players", {
                "server_id": self.server_id, "username": username, "uuid": uuid,
                "first_seen": now, "last_seen": now, "total_seconds": 0,
                "sessions": 1, "online": 1, "session_started": now,
            })
        self.db.insert("player_sessions", {
            "server_id": self.server_id, "username": username,
            "uuid": uuid, "joined_at": now, "left_at": None,
        })
        await self.bus.publish(Event(
            type="player_joined", message=f"{username} joined",
            data={"username": username, "uuid": uuid, "online": len(self.online())},
        ))

    async def player_left(self, username: str) -> None:
        now = time.time()
        self.mark_verified("leave observed in console")
        row = self.db.query_one(
            "SELECT * FROM players WHERE server_id = ? AND username = ?", (self.server_id, username)
        )
        session_seconds = 0.0
        if row and row.get("session_started"):
            session_seconds = max(now - float(row["session_started"]), 0.0)
        self.db.execute(
            "UPDATE players SET online = 0, session_started = NULL, last_seen = ?, "
            "total_seconds = total_seconds + ? WHERE server_id = ? AND username = ?",
            (now, session_seconds, self.server_id, username),
        )
        self.db.execute(
            "UPDATE player_sessions SET left_at = ? WHERE id = ("
            "  SELECT id FROM player_sessions WHERE server_id = ? AND username = ? AND left_at IS NULL"
            "  ORDER BY joined_at DESC LIMIT 1)",
            (now, self.server_id, username),
        )
        await self.bus.publish(Event(
            type="player_left", message=f"{username} left",
            data={"username": username, "session_seconds": session_seconds,
                  "online": len(self.online())},
        ))

    async def reconcile(self, usernames: list[str]) -> None:
        """Align stored state with an authoritative /list reply."""
        self.mark_verified("/list reply from the server")
        current = {p["username"] for p in self.online()}
        for name in usernames:
            if name not in current:
                await self.player_joined(name)
        for name in current - set(usernames):
            await self.player_left(name)

    async def clear_online(self) -> None:
        """Called when the server stops or crashes: nobody is online any more.

        Closing these sessions is itself a verified fact - the process is
        gone, so no one can be connected to it.
        """
        for player in self.online():
            await self.player_left(player["username"])
        self.mark_verified("server process is not running")

    # ------------------------------------------------------------------
    def online(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT username, uuid, session_started, total_seconds, sessions, first_seen, last_seen "
            "FROM players WHERE server_id = ? AND online = 1 ORDER BY session_started ASC",
            (self.server_id,),
        )
        now = time.time()
        for row in rows:
            row["session_seconds"] = now - float(row["session_started"]) if row.get("session_started") else 0
        return rows

    def all_players(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM players WHERE server_id = ? ORDER BY last_seen DESC LIMIT ?",
            (self.server_id, limit),
        )
        now = time.time()
        for row in rows:
            extra = now - float(row["session_started"]) if row.get("session_started") else 0
            row["session_seconds"] = extra
            row["total_seconds_live"] = float(row.get("total_seconds") or 0) + extra
        return rows

    def sessions(self, username: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if username:
            return self.db.query(
                "SELECT * FROM player_sessions WHERE server_id = ? AND username = ? "
                "ORDER BY joined_at DESC LIMIT ?",
                (self.server_id, username, limit),
            )
        return self.db.query(
            "SELECT * FROM player_sessions WHERE server_id = ? ORDER BY joined_at DESC LIMIT ?",
            (self.server_id, limit),
        )
