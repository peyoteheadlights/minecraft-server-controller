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
  * Helper accounts (friends with limited access) are rows in the accounts
    table, hashed exactly like the owner's password, signed in and locked
    out the same way. Their role and servers decide what they may do
    (agent/security/permissions.py).
  * The owner's password can be reset only on the PC itself
    (python -m installer.reset_password), which rewrites .env and signs
    every session out. A running agent notices the new .env and uses it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from collections import deque
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
        raise ValueError("The password needs at least 10 characters.")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(rounds),
            base64.b64encode(salt).decode(),
            base64.b64encode(derived).decode(),
        ]
    )


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
    role: str = "owner"  # owner | helper
    # The servers this account may use. None: every server.
    servers: frozenset[str] | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "kind": self.kind,
            "expires_at": self.expires_at,
            "role": self.role,
            "servers": sorted(self.servers) if self.servers is not None else None,
        }


# A helper's sign-in name: short, and safe to show anywhere.
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,31}$")
MAX_HELPERS = 20
_DUMMY: list[str] = []


def _dummy_hash() -> str:
    """Verified against when a username is unknown, so a wrong name takes as
    long as a wrong password and the timing doesn't say which names exist."""
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_urlsafe(16)))
    return _DUMMY[0]


class AccountError(ValueError):
    """A helper account can't be made or changed as asked."""


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401, retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after


class RateLimiter:
    """Sliding-window limit: at most ``limit`` accepted requests per caller
    in any ``window`` seconds.

    Rejected requests are not counted, so a client that keeps retrying is
    let back in as soon as its oldest accepted request leaves the window.
    Callers with no recent requests are forgotten.
    """

    # Sweep idle callers out at most this often.
    SWEEP_INTERVAL = 60.0

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = time.time()

    def check(self, key: str) -> None:
        now = time.time()
        self._sweep(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = int(self.window - (now - hits[0])) + 1
            raise AuthError(
                "That is too many tries at once. Wait a moment.", status=429, retry_after=retry
            )
        hits.append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self.SWEEP_INTERVAL:
            return
        self._last_sweep = now
        stale = [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= self.window]
        for key in stale:
            del self._hits[key]


class AuthManager:
    def __init__(self, config, db, bus=None):
        self.config = config
        self.db = db
        self.bus = bus
        self.api_rate = RateLimiter(
            config.security.rate_limit_requests,
            config.security.rate_limit_window,
        )
        self.login_rate = RateLimiter(10, 300.0)

        self._env_seen: int | None = self._env_stamp()

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.config.admin_password_hash or self.config.api_token)

    # -- the owner's password, which lives in .env --------------------------
    def _env_stamp(self) -> int | None:
        path = getattr(self.config, "env_path", None)
        try:
            return path.stat().st_mtime_ns if path else None
        except OSError:
            return None

    def _refresh_owner(self) -> None:
        """Pick up a password reset made on the PC while the agent runs: when
        .env has changed since it was last read, its owner lines win."""
        stamp = self._env_stamp()
        if stamp is None or stamp == self._env_seen:
            return
        self._env_seen = stamp
        try:
            text = self.config.env_path.read_text(encoding="utf-8")
        except OSError:
            return
        for raw in text.splitlines():
            key, _, value = raw.strip().partition("=")
            if key.strip() in ("MCSC_ADMIN_PASSWORD_HASH", "MCSC_ADMIN_USERNAME") and value:
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
        log.info("the owner's sign-in details in .env changed; using the new ones")

    @property
    def owner_username(self) -> str:
        self._refresh_owner()
        return self.config.admin_username

    def _is_owner_name(self, username: str) -> bool:
        return hmac.compare_digest(username.lower(), self.owner_username.lower())

    def _locked_out(self, user: str, source_ip: str) -> float | None:
        max_failed = self.config.security.max_failed_logins
        window = self.config.security.lockout_minutes * 60
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
        self.db.insert(
            "login_attempts",
            {
                "ts": time.time(),
                "user": user,
                "source_ip": source_ip,
                "success": 1 if success else 0,
            },
        )

    def failed_login_count(self, hours: float = 24) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM login_attempts WHERE success = 0 AND ts > ?",
            (time.time() - hours * 3600,),
        )
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    def login(
        self, username: str, password: str, source_ip: str = "", label: str = ""
    ) -> dict[str, Any]:
        username = (username or "").strip()[:64]
        self.login_rate.check(f"login:{source_ip or 'unknown'}")
        self._refresh_owner()
        if not self.config.admin_password_hash:
            raise AuthError(
                "No password is configured. Set MCSC_ADMIN_PASSWORD_HASH in the agent's .env file "
                "(use: python -m installer.make_secrets).",
                status=503,
            )
        account = None
        if not hmac.compare_digest(username, self.config.admin_username):
            account = self.account(username)
            if account:
                username = account["username"]  # helpers' names ignore capitals
        remaining = self._locked_out(username, source_ip)
        if remaining and remaining > 0:
            raise AuthError(
                f"Too many failed attempts. Try again in {int(remaining / 60) + 1} minutes.",
                status=429,
                retry_after=int(remaining),
            )
        if account is not None:
            password_ok = verify_password(password or "", account["password_hash"])
        elif hmac.compare_digest(username, self.config.admin_username):
            password_ok = verify_password(password or "", self.config.admin_password_hash)
        else:
            verify_password(password or "", _dummy_hash())
            password_ok = False
        if not password_ok:
            self._record_attempt(username, source_ip, False)
            self.db.audit("login_failed", user=username, source_ip=source_ip, result="denied")
            if self.bus:
                from ..events import Event

                self.bus.publish_soon(
                    Event(
                        type="auth_failure",
                        level="warn",
                        message=f"Failed sign-in for '{username}' from {source_ip or 'unknown address'}",
                        data={"username": username, "source_ip": source_ip},
                    )
                )
            raise AuthError("That username or password isn't right.")

        self._record_attempt(username, source_ip, True)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        hours = self.config.security.session_hours
        expires = time.time() + hours * 3600
        self.db.insert(
            "sessions",
            {
                "token_hash": token_hash(token),
                "user": username,
                "created_at": time.time(),
                "expires_at": expires,
                "last_used": time.time(),
                "source_ip": source_ip,
                "label": label[:80],
            },
        )
        self.db.audit("login", user=username, source_ip=source_ip)
        self.purge_expired()
        return {
            "token": token,
            "user": username,
            "expires_at": expires,
            "role": account["role"] if account else "owner",
        }

    def authenticate(self, token: str | None, source_ip: str = "") -> Principal:
        if not token:
            raise AuthError("You have to be signed in to do that.")
        api_token = self.config.api_token
        if api_token and hmac.compare_digest(token, api_token):
            return Principal(user="api-token", kind="api_token")
        digest = token_hash(token)
        row = self.db.query_one("SELECT * FROM sessions WHERE token_hash = ?", (digest,))
        if not row:
            raise AuthError("You've been signed out. Sign in again.")
        if row["expires_at"] < time.time():
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            raise AuthError("Your session has expired. Sign in again.")
        role, servers = self._role_of(row["user"])
        if role is None:
            # The helper account was removed: its sessions end with it.
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            raise AuthError("You've been signed out. Sign in again.")
        self.db.execute(
            "UPDATE sessions SET last_used = ? WHERE token_hash = ?", (time.time(), digest)
        )
        return Principal(
            user=row["user"],
            kind="session",
            token_hash=digest,
            expires_at=row["expires_at"],
            role=role,
            servers=servers,
        )

    def _role_of(self, user: str) -> tuple[str | None, frozenset[str] | None]:
        """The role and server limit of a signed-in name, or (None, None)
        when no such account exists any more."""
        self._refresh_owner()
        if hmac.compare_digest(user, self.config.admin_username):
            return "owner", None
        account = self.account(user)
        if not account:
            return None, None
        return account["role"], account["servers"]

    # -- helper accounts ---------------------------------------------------
    @staticmethod
    def _account_row(row: dict[str, Any]) -> dict[str, Any]:
        servers = json.loads(row["servers"]) if row.get("servers") else None
        return {**row, "servers": frozenset(servers) if servers is not None else None}

    def account(self, username: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM accounts WHERE username = ?", ((username or "")[:64],))
        return self._account_row(row) if row else None

    def accounts(self) -> list[dict[str, Any]]:
        """Every helper, without the password hashes."""
        rows = self.db.query("SELECT * FROM accounts ORDER BY username COLLATE NOCASE")
        out = []
        for row in rows:
            account = self._account_row(row)
            sessions = self.db.query_one(
                "SELECT COUNT(*) AS n, MAX(last_used) AS last FROM sessions "
                "WHERE user = ? AND expires_at > ?",
                (account["username"], time.time()),
            ) or {"n": 0, "last": None}
            last_login = self.db.query_one(
                "SELECT MAX(ts) AS ts FROM login_attempts WHERE user = ? AND success = 1",
                (account["username"],),
            )
            out.append(
                {
                    "username": account["username"],
                    "role": account["role"],
                    "servers": sorted(account["servers"]) if account["servers"] is not None else None,
                    "created_at": account["created_at"],
                    "created_by": account["created_by"],
                    "password_changed_at": account["password_changed_at"],
                    "active_sessions": int(sessions["n"] or 0),
                    "last_used": sessions["last"],
                    "last_sign_in": last_login["ts"] if last_login else None,
                }
            )
        return out

    def _check_new_password(self, password: str) -> str:
        if len(password or "") < 10:
            raise AccountError("The password needs at least 10 characters.")
        if len(password) > 256:
            raise AccountError("That password is too long.")
        return password

    def create_account(
        self, username: str, password: str, servers: list[str] | None, by: str
    ) -> dict[str, Any]:
        username = (username or "").strip()
        if not USERNAME_RE.match(username):
            raise AccountError(
                "A username is 2 to 32 letters, numbers, dots, dashes or underscores, "
                "starting with a letter or number."
            )
        if self._is_owner_name(username) or username.lower() == "api-token":
            raise AccountError("That name is already taken.")
        if self.account(username):
            raise AccountError(f"There is already a helper called {username}.")
        count = self.db.query_one("SELECT COUNT(*) AS n FROM accounts") or {"n": 0}
        if int(count["n"]) >= MAX_HELPERS:
            raise AccountError(f"There can be at most {MAX_HELPERS} helpers.")
        encoded = hash_password(self._check_new_password(password))
        now = time.time()
        self.db.insert(
            "accounts",
            {
                "username": username,
                "password_hash": encoded,
                "role": "helper",
                "servers": json.dumps(sorted(servers)) if servers is not None else None,
                "created_at": now,
                "created_by": by,
                "password_changed_at": now,
            },
        )
        self.db.audit("helper_added", user=by, target=username)
        return self.account(username) or {}

    def update_account(
        self,
        username: str,
        by: str,
        servers: list[str] | None | bool = False,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Change a helper's servers (``servers`` False: leave as is) or set
        a new password, which signs them out everywhere."""
        account = self.account(username)
        if not account:
            raise AccountError(f"There is no helper called {username}.")
        name = account["username"]
        if servers is not False:
            value = json.dumps(sorted(servers)) if isinstance(servers, list) else None
            self.db.execute("UPDATE accounts SET servers = ? WHERE username = ?", (value, name))
            self.db.audit("helper_servers", user=by, target=name, detail=value or "every server")
        if password is not None:
            encoded = hash_password(self._check_new_password(password))
            self.db.execute(
                "UPDATE accounts SET password_hash = ?, password_changed_at = ? WHERE username = ?",
                (encoded, time.time(), name),
            )
            self.db.execute("DELETE FROM sessions WHERE user = ?", (name,))
            self.db.audit("helper_password_set", user=by, target=name)
        return self.account(name) or {}

    def delete_account(self, username: str, by: str) -> str:
        account = self.account(username)
        if not account:
            raise AccountError(f"There is no helper called {username}.")
        name = account["username"]
        self.db.execute("DELETE FROM accounts WHERE username = ?", (name,))
        self.db.execute("DELETE FROM sessions WHERE user = ?", (name,))
        self.db.audit("helper_removed", user=by, target=name)
        return name

    def change_own_password(self, principal: Principal, current: str, new: str) -> None:
        """A helper changing their own password. Their other sessions end;
        this one stays signed in."""
        if principal.is_owner:
            raise AccountError(
                "The owner password is changed on the server PC: run "
                "python -m installer.reset_password there."
            )
        account = self.account(principal.user)
        if not account or not verify_password(current or "", account["password_hash"]):
            raise AuthError("Your current password isn't right.", status=400)
        encoded = hash_password(self._check_new_password(new))
        self.db.execute(
            "UPDATE accounts SET password_hash = ?, password_changed_at = ? WHERE username = ?",
            (encoded, time.time(), account["username"]),
        )
        self.db.execute(
            "DELETE FROM sessions WHERE user = ? AND token_hash != ?",
            (account["username"], principal.token_hash or ""),
        )
        self.db.audit("password_changed", user=account["username"])

    def rotate(self, principal: Principal, source_ip: str = "") -> dict[str, Any]:
        """Issue a fresh session token and invalidate the current one."""
        if principal.kind != "session" or not principal.token_hash:
            raise AuthError("Only a sign-in from a browser can be given a new key.", status=400)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        hours = self.config.security.session_hours
        expires = time.time() + hours * 3600
        self.db.insert(
            "sessions",
            {
                "token_hash": token_hash(token),
                "user": principal.user,
                "created_at": time.time(),
                "expires_at": expires,
                "last_used": time.time(),
                "source_ip": source_ip,
                "label": "rotated",
            },
        )
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

    # -- preferences -----------------------------------------------------
    # How each account likes the dashboard (Simple or Technical, theme),
    # kept here so the choice follows the person to every device.
    PREFERENCE_CHOICES: dict[str, tuple[str, ...]] = {
        "mode": ("simple", "technical"),
        "theme": ("system", "light", "dark", "graphite", "contrast"),
    }
    PREFERENCE_DEFAULTS: dict[str, str] = {"mode": "simple", "theme": "system"}

    def preferences(self, user: str) -> dict[str, str]:
        saved = self.db.get_setting(f"user:{user}:preferences", {}) or {}
        prefs = dict(self.PREFERENCE_DEFAULTS)
        for key, choices in self.PREFERENCE_CHOICES.items():
            if saved.get(key) in choices:
                prefs[key] = saved[key]
        return prefs

    def set_preferences(self, user: str, updates: dict[str, str]) -> dict[str, str]:
        prefs = self.preferences(user)
        for key, value in updates.items():
            if value not in self.PREFERENCE_CHOICES.get(key, ()):
                raise ValueError(f"{value!r} is not a choice for {key}")
            prefs[key] = value
        self.db.set_setting(f"user:{user}:preferences", prefs)
        return prefs

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
