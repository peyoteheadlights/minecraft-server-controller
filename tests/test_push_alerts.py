"""Phase 5: phone alerts (Web Push).

The encryption and the signed token are checked against what the standards
say the push service will see, and the dispatcher's behaviour is checked
against what a push service answers. No test reaches the network: the
module's TRANSPORT is swapped for a mock, exactly as the downloader does.
"""

import base64
import json
import os
import struct

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from agent.database.db import Database
from agent.events import Event, EventBus
from agent.minecraft.process import MinecraftServer
from agent.notifications import push
from agent.notifications.dispatcher import Notifier


@pytest.fixture
def db(config):
    database = Database(config.database_path)
    database.register_server("test", "Test", str(config.server_dir))
    yield database
    database.close()


@pytest.fixture
def keys(monkeypatch):
    public, private = push.generate_keys()
    monkeypatch.setenv("MCSC_VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("MCSC_VAPID_PRIVATE_KEY", private)
    monkeypatch.setenv("MCSC_PUSH_SUBJECT", "mailto:owner@example.com")
    return public, private


def browser_subscription(endpoint="https://push.example/send/abc"):
    """What a browser's PushSubscription.toJSON() looks like, with a real
    key pair so the result can be decrypted again."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    payload = {
        "endpoint": endpoint,
        "keys": {
            "p256dh": base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
            "auth": base64.urlsafe_b64encode(auth).rstrip(b"=").decode(),
        },
    }
    return payload, private


def decrypt(body, private_key, auth_secret):
    """The browser's half of RFC 8291, so the test reads what a phone would."""
    salt, rest = body[:16], body[16:]
    _record_size, key_length = struct.unpack("!LB", rest[:5])
    sender_public_raw = rest[5 : 5 + key_length]
    ciphertext = rest[5 + key_length :]
    client_public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = private_key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_public_raw)
    )
    prk = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + client_public_raw + sender_public_raw,
    ).derive(shared)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(prk)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00"
    ).derive(prk)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plain.rstrip(b"\x02")


# ------------------------------------------------------------- the standards
def test_a_message_can_only_be_read_by_the_phone_it_was_sent_to():
    payload, private = browser_subscription()
    auth = push.unb64(payload["keys"]["auth"])
    body = push.encrypt(
        b'{"title":"Survival stopped"}', payload["keys"]["p256dh"], payload["keys"]["auth"]
    )

    assert decrypt(body, private, auth) == b'{"title":"Survival stopped"}'
    # Another phone's keys do not open it.
    _other_payload, other_private = browser_subscription()
    with pytest.raises(InvalidTag):
        decrypt(body, other_private, auth)


def test_every_message_is_encrypted_with_a_fresh_salt():
    payload, _private = browser_subscription()
    one = push.encrypt(b"hello", payload["keys"]["p256dh"], payload["keys"]["auth"])
    two = push.encrypt(b"hello", payload["keys"]["p256dh"], payload["keys"]["auth"])
    assert one[:16] != two[:16]
    assert one != two


def test_the_token_says_who_is_sending_and_can_be_checked():
    public, private = push.generate_keys()
    headers = push.vapid_headers(
        "https://push.example/send/abc", public, private, "mailto:owner@example.com"
    )
    scheme, _, rest = headers["Authorization"].partition(" ")
    assert scheme == "vapid"
    parts = dict(p.strip().split("=", 1) for p in rest.split(","))
    assert parts["k"] == public
    header_b64, claims_b64, signature_b64 = parts["t"].split(".")
    claims = json.loads(push.unb64(claims_b64))
    assert claims["aud"] == "https://push.example"
    assert claims["sub"] == "mailto:owner@example.com"
    assert json.loads(push.unb64(header_b64))["alg"] == "ES256"

    # The push service verifies the signature with the public key it is given.
    signature = push.unb64(signature_b64)
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64(public))
    key.verify(
        utils.encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        ),
        f"{header_b64}.{claims_b64}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )


def test_a_bad_private_key_is_reported_in_words():
    with pytest.raises(push.PushError, match="make_push_keys"):
        push.vapid_headers("https://push.example/x", "pub", "!!!", "")


# ---------------------------------------------------------- what is accepted
def test_only_a_real_https_push_address_is_accepted():
    good, _private = browser_subscription()
    assert push.Subscription.from_browser(good).endpoint == good["endpoint"]

    for bad_endpoint in ("http://push.example/send/abc", "file:///etc/passwd", "", "not a url"):
        payload = {**good, "endpoint": bad_endpoint}
        with pytest.raises(push.PushError):
            push.Subscription.from_browser(payload)


def test_keys_that_are_not_the_expected_size_are_refused():
    good, _private = browser_subscription()
    for keys in (
        {"p256dh": "aGk", "auth": good["keys"]["auth"]},
        {"p256dh": good["keys"]["p256dh"], "auth": "aGk"},
        {},
    ):
        with pytest.raises(push.PushError):
            push.Subscription.from_browser({**good, "keys": keys})


def test_there_is_a_limit_on_how_many_phones_sign_up(db):
    for index in range(push.MAX_SUBSCRIPTIONS):
        payload, _private = browser_subscription(f"https://push.example/send/{index}")
        push.store(db, push.Subscription.from_browser(payload), user="admin")
    payload, _private = browser_subscription("https://push.example/send/one-too-many")
    with pytest.raises(push.PushError, match="already"):
        push.store(db, push.Subscription.from_browser(payload), user="admin")


def test_signing_up_the_same_phone_twice_refreshes_it(db):
    payload, _private = browser_subscription()
    push.store(db, push.Subscription.from_browser(payload, label="Phone"), user="admin")
    again, _private2 = browser_subscription()
    again["endpoint"] = payload["endpoint"]
    push.store(db, push.Subscription.from_browser(again, label="Same phone"), user="admin")

    listed = push.listed(db)
    assert len(listed) == 1
    assert listed[0]["label"] == "Same phone"
    # The list never hands the phone's keys back out.
    assert "p256dh" not in listed[0] and "auth" not in listed[0]
    assert listed[0]["service"] == "push.example"


# ----------------------------------------------------------------- sending
async def test_a_phone_the_service_says_is_gone_is_forgotten(config, db, keys, monkeypatch):
    config.set("notifications.push_enabled", True)
    payload, _private = browser_subscription()
    push.store(db, push.Subscription.from_browser(payload, label="Old phone"), user="admin")

    monkeypatch.setattr(push, "TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(410)))
    bus = EventBus()
    notifier = Notifier(config, bus, db, MinecraftServer(config, bus, db))

    assert await notifier.send_push(Event(type="server_crashed", message="boom")) is False
    assert push.listed(db) == []


async def test_a_phone_that_simply_failed_is_kept(config, db, keys, monkeypatch):
    config.set("notifications.push_enabled", True)
    payload, _private = browser_subscription()
    push.store(db, push.Subscription.from_browser(payload), user="admin")

    monkeypatch.setattr(push, "TRANSPORT", httpx.MockTransport(lambda request: httpx.Response(500)))
    bus = EventBus()
    notifier = Notifier(config, bus, db, MinecraftServer(config, bus, db))

    assert await notifier.send_push(Event(type="server_crashed", message="boom")) is False
    assert len(push.listed(db)) == 1
    assert push.listed(db)[0]["last_result"]


async def test_a_sent_alert_carries_the_message_and_is_remembered(config, db, keys, monkeypatch):
    config.set("notifications.push_enabled", True)
    payload, private = browser_subscription()
    auth = push.unb64(payload["keys"]["auth"])
    push.store(db, push.Subscription.from_browser(payload, label="Pixel"), user="admin")

    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(201)

    monkeypatch.setattr(push, "TRANSPORT", httpx.MockTransport(handler))
    bus = EventBus()
    notifier = Notifier(config, bus, db, MinecraftServer(config, bus, db))

    assert (
        await notifier.send_push(Event(type="server_crashed", message="Survival crashed")) is True
    )
    assert seen["headers"]["content-encoding"] == "aes128gcm"
    assert seen["headers"]["ttl"] == str(push.TTL_SECONDS)
    message = json.loads(decrypt(seen["body"], private, auth))
    assert "Survival crashed" in json.dumps(message)
    assert push.listed(db)[0]["last_result"] == "sent"
    assert push.listed(db)[0]["last_sent"]


async def test_nothing_is_sent_without_keys(config, db, monkeypatch):
    config.set("notifications.push_enabled", True)
    monkeypatch.delenv("MCSC_VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("MCSC_VAPID_PUBLIC_KEY", raising=False)
    payload, _private = browser_subscription()
    push.store(db, push.Subscription.from_browser(payload), user="admin")

    def explode(request):  # pragma: no cover - must never be reached
        raise AssertionError("a push was sent without keys")

    monkeypatch.setattr(push, "TRANSPORT", httpx.MockTransport(explode))
    bus = EventBus()
    notifier = Notifier(config, bus, db, MinecraftServer(config, bus, db))
    assert await notifier.send_push(Event(type="server_crashed", message="boom")) is False


# -------------------------------------------------------------------- the API
def login(client):
    from .conftest import PASSWORD

    token = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "token"
    ]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_phone_alerts_are_off_and_unset_until_the_owner_sets_them_up(client):
    login(client)
    state = client.get("/api/push").json()
    assert state["configured"] is False
    assert state["enabled"] is False
    assert state["phones"] == []
    assert "make_push_keys" in state["setup_command"]

    payload, _private = browser_subscription()
    answer = client.post("/api/push/subscribe", json={"subscription": payload, "label": "Phone"})
    assert answer.status_code == 409
    assert "make_push_keys" in answer.json()["detail"]


def test_a_phone_can_sign_up_and_leave(client, keys):
    login(client)
    assert client.get("/api/push").json()["configured"] is True

    payload, _private = browser_subscription()
    answer = client.post("/api/push/subscribe", json={"subscription": payload, "label": "Pixel"})
    assert answer.status_code == 200
    assert [p["label"] for p in answer.json()["phones"]] == ["Pixel"]
    # The private half of the app's key pair is never served.
    state = client.get("/api/push").json()
    assert state["public_key"] and "private" not in json.dumps(state)

    gone = client.post("/api/push/unsubscribe", json={"endpoint": payload["endpoint"]})
    assert gone.json()["removed"] is True
    assert gone.json()["phones"] == []


def test_the_test_alert_goes_to_the_phones_that_signed_up(client, keys, monkeypatch):
    login(client)
    payload, _private = browser_subscription()
    client.post("/api/push/subscribe", json={"subscription": payload, "label": "Pixel"})

    calls = []
    monkeypatch.setattr(
        push,
        "TRANSPORT",
        httpx.MockTransport(lambda request: (calls.append(request.url), httpx.Response(201))[1]),
    )
    answer = client.post("/api/push/test").json()
    assert answer["sent"] is True
    assert len(calls) == 1


def test_signing_up_needs_permission(client, keys):
    login(client)
    payload, _private = browser_subscription()
    client.headers.pop("Authorization")
    assert client.post("/api/push/subscribe", json={"subscription": payload}).status_code in (
        401,
        403,
    )
