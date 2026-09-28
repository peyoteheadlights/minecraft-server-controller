"""Authentication and rate limiting.

Design:

  * The operator signs in with a username and password. The password is never
    stored - only a PBKDF2-HMAC-SHA256 hash with a per-install salt, taken
    from the MCSC_ADMIN_PASSWORD_HASH environment variable.
  * A successful sign-in returns a random 256-bit session token. Only the
    SHA-256 of that token is stored, so a stolen database yields no usable
    tokens.
  * A long-lived API token (MCSC_API_TOKEN) is supported for scripts. It is
    compared in constant time.
  * Failed attempts are counted per username and per source address, and a
    lockout applies after a configurable number.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("msc.auth")

PBKDF2_ROUNDS = 240_000
TOKEN_BYTES = 32


# ----------------------------------------------------------------------
# password hashing
# ----------------------------------------------------------------------
def hash_password(password: str, salt: bytes | None = None, rounds: int = PBKDF2_ROUNDS) -> str:
    """Return a self-describing hash string: pbkdf2_sha256$rounds$salt$hash."""
    if len(password) < 10:
        raise ValueError("The password must be at least 10 characters long")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "$".join([
        "pbkdf2_sha256", str(rounds),
        base64.b64encode(salt).decode(), base64.b64encode(derived).decode(),
    ])


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(rounds)
        )
        return hmac.compare_digest(derived, base64.b64decode(hash_b64))
    except (ValueError, TypeError, AttributeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
@dataclass
class Principal:
    user: str
    kind: str  # session | api_token
    token_hash: str | None = None
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"user": self.user, "kind": self.kind, "expires_at": self.expires_at}


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after


class RateLimiter:
    """Fixed-window counter keyed by caller identity."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(hits) >= self.limit:
            retry = int(self.window - (now - hits[0])) + 1
            hits.append(now)
            self._hits[key] = hits
            raise AuthError("Too many requests. Slow down.", status=429, retry_after=retry)
        hits.append(now)
        self._hits[key] = hits

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


class AuthManager:
    def __init__(self, config, db, bus=None):
        self.config = config
        self.db = db
        self.bus = bus
        self.api_rate = RateLimiter(
            int(config.get("security.rate_limit_requests", 120)),
            float(config.get("security.rate_limit_window", 60)),
        )
        self.login_rate = RateLimiter(10, 300.0)

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.config.admin_password_hash or self.config.api_token)

    def _locked_out(self, user: str, source_ip: str) -> float | None:
        max_failed = int(self.config.get("security.max_failed_logins", 5))
        window = float(self.config.get("security.lockout_minutes", 15)) * 60
        cutoff = time.time() - window
        rows = self.db.query(
            "SELECT ts FROM login_attempts WHERE success = 0 AND ts > ? AND (user = ? OR source_ip = ?) "
            "ORDER BY ts DESC",
            (cutoff, user, source_ip),
        )
        if len(rows) >= max_failed:
            return rows[0]["ts"] + window - time.time()
        return None

    def _record_attempt(self, user: str, source_ip: str, success: bool) -> None:
        self.db.insert("login_attempts", {
            "ts": time.time(), "user": user, "source_ip": source_ip,
            "success": 1 if success else 0,
        })

    def failed_login_count(self, hours: float = 24) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM login_attempts WHERE success = 0 AND ts > ?",
            (time.time() - hours * 3600,),
        )
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    def login(self, username: str, password: str, source_ip: str = "",
              label: str = "") -> dict[str, Any]:
        username = (username or "").strip()[:64]
        self.login_rate.check(f"login:{source_ip or 'unknown'}")
        if not self.config.admin_password_hash:
            raise AuthError(
                "No password is configured. Set MCSC_ADMIN_PASSWORD_HASH in the agent's .env file "
                "(use: python -m installer.make_secrets).",
                status=503,
            )
        remaining = self._locked_out(username, source_ip)
        if remaining and remaining > 0:
            raise AuthError(
                f"Too many failed attempts. Try again in {int(remaining/60)+1} minutes.",
                status=429, retry_after=int(remaining),
            )
        expected_user = self.config.admin_username
        user_ok = hmac.compare_digest(username, expected_user)
        password_ok = verify_password(password or "", self.config.admin_password_hash)
        if not (user_ok and password_ok):
            self._record_attempt(username, source_ip, False)
            self.db.audit("login_failed", user=username, source_ip=source_ip, result="denied")
            if self.bus:
                from ..events import Event
                self.bus.publish_soon(Event(
                    type="auth_failure", level="warn",
                    message=f"Failed sign-in for '{username}' from {source_ip or 'unknown address'}",
                    data={"username": username, "source_ip": source_ip},
                ))
            raise AuthError("The username or password is not correct")

        self._record_attempt(username, source_ip, True)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        hours = float(self.config.get("security.session_hours", 12))
        expires = time.time() + hours * 3600
        self.db.insert("sessions", {
            "token_hash": token_hash(token), "user": username,
            "created_at": time.time(), "expires_at": expires,
            "last_used": time.time(), "source_ip": source_ip, "label": label[:80],
        })
        self.db.audit("login", user=username, source_ip=source_ip)
        self.purge_expired()
        return {"token": token, "user": username, "expires_at": expires}

    def authenticate(self, token: str | None, source_ip: str = "") -> Principal:
        if not token:
            raise AuthError("This request needs a valid token")
        api_token = self.config.api_token
        if api_token and hmac.compare_digest(token, api_token):
            return Principal(user="api-token", kind="api_token")
        digest = token_hash(token)
        row = self.db.query_one("SELECT * FROM sessions WHERE token_hash = ?", (digest,))
        if not row:
            raise AuthError("Your session is not valid. Sign in again.")
        if row["expires_at"] < time.time():
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            raise AuthError("Your session has expired. Sign in again.")
        self.db.execute(
            "UPDATE sessions SET last_used = ? WHERE token_hash = ?", (time.time(), digest)
        )
        return Principal(user=row["user"], kind="session", token_hash=digest,
                         expires_at=row["expires_at"])

    def rotate(self, principal: Principal, source_ip: str = "") -> dict[str, Any]:
        """Issue a fresh session token and invalidate the current one."""
        if principal.kind != "session" or not principal.token_hash:
            raise AuthError("Only interactive sessions can be rotated", status=400)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        hours = float(self.config.get("security.session_hours", 12))
        expires = time.time() + hours * 3600
        self.db.insert("sessions", {
            "token_hash": token_hash(token), "user": principal.user,
            "created_at": time.time(), "expires_at": expires,
            "last_used": time.time(), "source_ip": source_ip, "label": "rotated",
        })
        self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (principal.token_hash,))
        self.db.audit("token_rotate", user=principal.user, source_ip=source_ip)
        return {"token": token, "expires_at": expires}

    def logout(self, principal: Principal) -> None:
        if principal.token_hash:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (principal.token_hash,))
            self.db.audit("logout", user=principal.user)

    def revoke_all(self, user: str | None = None) -> int:
        if user:
            cur = self.db.execute("DELETE FROM sessions WHERE user = ?", (user,))
        else:
            cur = self.db.execute("DELETE FROM sessions", ())
        self.db.audit("sessions_revoked", user=user or "all")
        return cur.rowcount

    def purge_expired(self) -> int:
        cur = self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        return cur.rowcount

    def active_sessions(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT user, created_at, expires_at, last_used, source_ip, label FROM sessions "
            "WHERE expires_at > ? ORDER BY last_used DESC",
            (time.time(),),
        )
        return rows
