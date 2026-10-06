"""Phone alerts: Web Push notifications to browsers that subscribed.

A third channel next to Discord and email, for the same events and the same
cooldowns. It is the only one that reaches a phone's lock screen without an
account anywhere: the browser gives this app an endpoint on its own push
service, and this module posts encrypted messages to it.

Two standards do the work, and both are implemented here with
``cryptography`` rather than another dependency:

  * RFC 8292 (VAPID): every request carries a signed token saying who is
    sending, so a push service can tell this app's messages apart from
    anyone else's. The keys live in ``.env`` like the other secrets, and
    are made by ``python -m installer.make_push_keys``.
  * RFC 8291 (message encryption): the message is encrypted for that one
    subscription with a key agreed with the browser, so the push service
    carries text it cannot read.

Subscriptions are rows in the database. A push service answering 404 or 410
means the browser is gone for good, and the row is deleted; nothing else
removes one by itself.

Nothing here can take the agent down: every send is wrapped by the Notifier,
and no test touches the network (``TRANSPORT`` is swapped for a mock).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger("msc.push")

# Swapped for an httpx.MockTransport in the tests, exactly as the
# downloader does, so no test ever reaches a real push service.
TRANSPORT: httpx.AsyncBaseTransport | None = None

# How long a push service should hold a message for a phone that is off.
TTL_SECONDS = 600
# The VAPID token's lifetime. Push services refuse more than 24 hours.
TOKEN_SECONDS = 12 * 3600
RECORD_SIZE = 4096
TIMEOUT = 15.0
# A push endpoint has to be an HTTPS URL on the browser's own push service.
ALLOWED_SCHEMES = ("https",)


class PushError(RuntimeError):
    """Written for people: why a phone alert could not be sent or stored."""


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text.replace("+", "-").replace("/", "_") + padding)


# ----------------------------------------------------------------------
# keys
# ----------------------------------------------------------------------
def generate_keys() -> tuple[str, str]:
    """A new (public, private) VAPID key pair, base64url, as the browser
    and the push services expect them."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    secret = private.private_numbers().private_value.to_bytes(32, "big")
    return b64(public), b64(secret)


def load_private_key(encoded: str) -> ec.EllipticCurvePrivateKey:
    try:
        return ec.derive_private_key(int.from_bytes(unb64(encoded), "big"), ec.SECP256R1())
    except (ValueError, TypeError) as exc:
        raise PushError(
            "MCSC_VAPID_PRIVATE_KEY is not a key this app can read. Make a new pair with "
            "python -m installer.make_push_keys"
        ) from exc


@dataclass(frozen=True)
class Subscription:
    """One browser's push subscription, as the browser described it."""

    endpoint: str
    p256dh: str  # the browser's public key, base64url
    auth: str  # the browser's shared secret, base64url
    label: str = ""

    @classmethod
    def from_browser(cls, data: dict[str, Any], label: str = "") -> Subscription:
        endpoint = str((data or {}).get("endpoint") or "").strip()
        keys = (data or {}).get("keys") or {}
        p256dh = str(keys.get("p256dh") or "").strip()
        auth = str(keys.get("auth") or "").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
            raise PushError("That isn't a push address this app can send to.")
        if len(endpoint) > 1000:
            raise PushError("That push address is far longer than any browser sends.")
        try:
            if len(unb64(p256dh)) != 65 or len(unb64(auth)) != 16:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise PushError("The phone's push keys were not in the expected form.") from exc
        return cls(endpoint=endpoint, p256dh=p256dh, auth=auth, label=label[:80])


# ----------------------------------------------------------------------
# RFC 8291: encrypting one message for one subscription
# ----------------------------------------------------------------------
def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """The aes128gcm body of a push message, for that subscription only."""
    client_public_raw = unb64(p256dh)
    client_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), client_public_raw)
    ephemeral = ec.generate_private_key(ec.SECP256R1())
    ephemeral_public_raw = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = ephemeral.exchange(ec.ECDH(), client_public)

    # The key the two sides agree on, bound to both public keys so a
    # message encrypted for one phone cannot be replayed at another.
    prk = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=unb64(auth),
        info=b"WebPush: info\x00" + client_public_raw + ephemeral_public_raw,
    ).derive(shared)
    salt = os.urandom(16)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(prk)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00"
    ).derive(prk)

    # One record, so the padding delimiter is the last-record one (0x02).
    body = AESGCM(key).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!LB", RECORD_SIZE, len(ephemeral_public_raw))
    return header + ephemeral_public_raw + body


# ----------------------------------------------------------------------
# RFC 8292: saying who is sending
# ----------------------------------------------------------------------
def vapid_headers(endpoint: str, public_key: str, private_key: str, subject: str) -> dict[str, str]:
    key = load_private_key(private_key)
    parsed = urlparse(endpoint)
    claims = {
        "aud": f"{parsed.scheme}://{parsed.netloc}",
        "exp": int(time.time() + TOKEN_SECONDS),
        "sub": subject or "mailto:admin@localhost",
    }
    signing_input = b".".join(
        [
            b64(
                json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()
            ).encode(),
            b64(json.dumps(claims, separators=(",", ":")).encode()).encode(),
        ]
    )
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = signing_input.decode("ascii") + "." + b64(signature)
    return {"Authorization": f"vapid t={token}, k={public_key}"}


# ----------------------------------------------------------------------
# sending
# ----------------------------------------------------------------------
@dataclass
class PushResult:
    ok: bool
    status: int | None
    detail: str = ""
    # True when the push service said this subscription is gone for good.
    gone: bool = False


async def send(
    subscription: Subscription,
    message: dict[str, Any],
    public_key: str,
    private_key: str,
    subject: str,
) -> PushResult:
    """Post one encrypted message. Never raises for a failed send."""
    if not public_key or not private_key:
        return PushResult(False, None, "No phone-alert keys are set up")
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    try:
        body = encrypt(payload, subscription.p256dh, subscription.auth)
        headers = {
            **vapid_headers(subscription.endpoint, public_key, private_key, subject),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SECONDS),
            "Urgency": "normal",
        }
    except (PushError, ValueError) as exc:
        return PushResult(False, None, str(exc))
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT) as client:
            response = await client.post(subscription.endpoint, content=body, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        return PushResult(False, None, str(exc))
    if response.status_code in (404, 410):
        return PushResult(False, response.status_code, "The phone is no longer subscribed", True)
    if response.status_code >= 400:
        return PushResult(False, response.status_code, f"HTTP {response.status_code}")
    return PushResult(True, response.status_code)


# ----------------------------------------------------------------------
# where subscriptions are kept
# ----------------------------------------------------------------------
MAX_SUBSCRIPTIONS = 20


def store(db, subscription: Subscription, user: str) -> dict[str, Any]:
    """Remember one browser's subscription (or refresh it if it is known)."""
    if (
        db.query_one(
            "SELECT COUNT(*) AS n FROM push_subscriptions WHERE endpoint != ?",
            (subscription.endpoint,),
        )
        or {}
    ).get("n", 0) >= MAX_SUBSCRIPTIONS:
        raise PushError(
            f"There are already {MAX_SUBSCRIPTIONS} phones signed up for alerts. Remove one first."
        )
    db.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, user, label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint) DO UPDATE SET "
        "p256dh=excluded.p256dh, auth=excluded.auth, user=excluded.user, label=excluded.label",
        (
            subscription.endpoint,
            subscription.p256dh,
            subscription.auth,
            user,
            subscription.label,
            time.time(),
        ),
    )
    return {"endpoint": subscription.endpoint, "label": subscription.label}


def forget(db, endpoint: str) -> bool:
    cursor = db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    return bool(cursor.rowcount)


def subscriptions(db) -> list[Subscription]:
    return [
        Subscription(
            endpoint=row["endpoint"],
            p256dh=row["p256dh"],
            auth=row["auth"],
            label=row["label"] or "",
        )
        for row in db.query("SELECT * FROM push_subscriptions ORDER BY created_at")
    ]


def listed(db) -> list[dict[str, Any]]:
    """What the Settings page shows: which phones are signed up, with no
    keys in the answer."""
    return [
        {
            "endpoint": row["endpoint"],
            "label": row["label"] or "",
            "user": row["user"],
            "created_at": row["created_at"],
            "last_sent": row["last_sent"],
            "last_result": row["last_result"],
            # Enough to recognise a phone without handing the address out.
            "service": urlparse(row["endpoint"]).netloc,
        }
        for row in db.query("SELECT * FROM push_subscriptions ORDER BY created_at")
    ]


def record_result(db, endpoint: str, result: PushResult) -> None:
    db.execute(
        "UPDATE push_subscriptions SET last_sent = ?, last_result = ? WHERE endpoint = ?",
        (time.time(), "sent" if result.ok else (result.detail or "failed")[:200], endpoint),
    )
