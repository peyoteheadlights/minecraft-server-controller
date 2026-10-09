"""Lock-screen alerts for the phone app, through Google's push service (FCM).

The agent sends straight to FCM: no relay and nobody else's server. Each
message carries no words, only "there is a new alert" and its number. The
phone wakes, reads the alert itself from ``/api/alerts`` over Tailscale and
shows it. So Google sees which phone is woken and when, never a server's
name, a player or a message.

Setting it up needs one file from the owner's own Firebase project, its
service account key (see mobile/README.md). It lives only in the data
folder, in a folder only this account can read
(``python -m installer.setup_phone_alerts <file>`` puts it there). Without
it, nothing here sends anything and the app still catches up when opened.

Phones are rows in ``app_phones``, each tied to the sign-in (session) it
registered with: when that session ends (signed out in the app or on the
PC, a helper removed), the row goes with it, so a signed-out phone is never
woken again. FCM answering that a phone's address is gone deletes the row.

Only two addresses are ever contacted, both fixed here, and no test touches
the network (``TRANSPORT`` is swapped for a mock).
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

log = logging.getLogger("msc.fcm")

# Swapped for an httpx.MockTransport in the tests.
TRANSPORT: httpx.AsyncBaseTransport | None = None

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
KEY_FILE = "phone-alerts/fcm-service-account.json"
TIMEOUT = 15.0
# How long FCM keeps trying a phone that is off before dropping the wake-up.
# The app catches up when it opens anyway.
TTL = "3600s"
MAX_PHONES = 20
PLATFORMS = ("android", "ios")


class FcmError(Exception):
    pass


@dataclass(frozen=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: rsa.RSAPrivateKey


def key_path(config) -> Path:
    return config.resolve_data(KEY_FILE)


def load_service_account(path: Path) -> ServiceAccount:
    """The Firebase service account key, checked. Raises FcmError with a
    plain reason; the key itself never appears in a message or a log."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FcmError("Phone alerts through Google aren't set up on this PC.") from exc
    except (OSError, ValueError) as exc:
        raise FcmError("The Firebase key file can't be read.") from exc
    if not isinstance(data, dict) or data.get("type") != "service_account":
        raise FcmError("That file isn't a Firebase service account key.")
    for name in ("project_id", "client_email", "private_key"):
        if not isinstance(data.get(name), str) or not data[name]:
            raise FcmError(f"The Firebase key file has no {name}.")
    # The token address is fixed: a key file naming another one is refused
    # rather than followed, so the private key's signature only goes to Google.
    if data.get("token_uri", TOKEN_URL) != TOKEN_URL:
        raise FcmError("The Firebase key file names an unexpected sign-in address.")
    try:
        key = serialization.load_pem_private_key(data["private_key"].encode(), password=None)
    except ValueError as exc:
        raise FcmError("The Firebase key file's private key can't be read.") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise FcmError("The Firebase key file's private key isn't an RSA key.")
    return ServiceAccount(data["project_id"], data["client_email"], key)


def configured(config) -> bool:
    try:
        load_service_account(key_path(config))
    except FcmError:
        return False
    return True


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def assertion(account: ServiceAccount, now: float | None = None) -> str:
    """The signed request for an access token (RFC 7523, RS256)."""
    now = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": account.client_email,
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        _b64(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = account.private_key.sign(
        signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return signing_input + "." + _b64(signature)


@dataclass
class SendResult:
    ok: bool
    gone: bool = False
    detail: str = ""


class Sender:
    """Sends wake-ups, reusing an access token until shortly before it ends."""

    def __init__(self, config):
        self.config = config
        self._token: str | None = None
        self._token_until = 0.0

    async def _access_token(self, client: httpx.AsyncClient, account: ServiceAccount) -> str:
        if self._token and time.time() < self._token_until - 60:
            return self._token
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion(account),
            },
        )
        if response.status_code != 200:
            raise FcmError(f"Google refused the Firebase key (HTTP {response.status_code}).")
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise FcmError("Google's answer had no access token.")
        self._token = token
        self._token_until = time.time() + float(body.get("expires_in", 3600))
        return token

    async def wake(self, phone_tokens: list[str], alert_id: int) -> dict[str, SendResult]:
        """Wake each phone about alert ``alert_id``. Never raises."""
        results: dict[str, SendResult] = {}
        if not phone_tokens:
            return results
        try:
            account = load_service_account(key_path(self.config))
        except FcmError as exc:
            return {t: SendResult(False, detail=str(exc)) for t in phone_tokens}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT) as client:
                access = await self._access_token(client, account)
                url = SEND_URL.format(project=account.project_id)
                for phone in phone_tokens:
                    results[phone] = await self._send_one(client, url, access, phone, alert_id)
        except (FcmError, httpx.HTTPError) as exc:
            detail = (
                str(exc) if isinstance(exc, FcmError) else "Google's push service didn't answer."
            )
            for phone in phone_tokens:
                results.setdefault(phone, SendResult(False, detail=detail))
        return results

    async def _send_one(
        self, client: httpx.AsyncClient, url: str, access: str, phone: str, alert_id: int
    ) -> SendResult:
        message = {
            "message": {
                "token": phone,
                # No words: the phone reads the alert from the PC itself.
                "data": {"kind": "alert", "alert": str(int(alert_id))},
                "android": {"priority": "high", "ttl": TTL},
                "apns": {
                    "headers": {"apns-priority": "10"},
                    # Lets the iPhone app's extension fetch the words first.
                    "payload": {"aps": {"mutable-content": 1, "alert": {"body": "New alert"}}},
                },
            }
        }
        response = await client.post(
            url, json=message, headers={"Authorization": f"Bearer {access}"}
        )
        if response.status_code == 200:
            return SendResult(True)
        status = _error_status(response)
        if response.status_code == 404 or status in ("UNREGISTERED", "NOT_FOUND"):
            return SendResult(
                False, gone=True, detail="This phone's push address is no longer valid."
            )
        if response.status_code == 401:
            self._token = None
        return SendResult(
            False, detail=f"Google's push service answered HTTP {response.status_code}."
        )


def _error_status(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details", []) if isinstance(error, dict) else []
    for item in details if isinstance(details, list) else []:
        if isinstance(item, dict) and item.get("errorCode"):
            return str(item["errorCode"])
    return str(error.get("status", "")) if isinstance(error, dict) else ""


# ---------------------------------------------------------------- phones
def register(db, session: str, user: str, token: str, platform: str, label: str) -> dict[str, Any]:
    """Remember a phone's push address for this sign-in. Registering the
    same address again (a new sign-in on the same phone) moves it."""
    now = time.time()
    db.execute("DELETE FROM app_phones WHERE token = ?", (token,))
    # One address per sign-in: a phone whose address changed replaces it.
    db.execute("DELETE FROM app_phones WHERE session = ?", (session,))
    db.insert(
        "app_phones",
        {
            "token": token,
            "session": session,
            "user": user,
            "platform": platform,
            "label": label[:80],
            "created_at": now,
        },
    )
    return {"platform": platform, "label": label[:80], "created_at": now}


def forget_session(db, session: str) -> bool:
    return db.execute("DELETE FROM app_phones WHERE session = ?", (session,)).rowcount > 0


def forget(db, token: str) -> None:
    db.execute("DELETE FROM app_phones WHERE token = ?", (token,))


def phones(db) -> list[dict[str, Any]]:
    return db.query("SELECT token, user, platform, label FROM app_phones ORDER BY created_at")


def count(db) -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM app_phones")
    return int(row["n"]) if row else 0


def record_result(db, token: str, result: SendResult) -> None:
    db.execute(
        "UPDATE app_phones SET last_sent = ?, last_result = ? WHERE token = ?",
        (time.time(), "ok" if result.ok else result.detail[:200], token),
    )
