"""Every API answer carries a request ID; error answers repeat it in their
body, and log lines written while handling the request end with it."""

import logging

from fastapi import APIRouter

from agent import requestid
from agent.requestid import RequestIdFilter


def test_every_answer_has_an_id(client):
    response = client.get("/")
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 12
    other = client.get("/")
    assert other.headers["X-Request-ID"] != response.headers["X-Request-ID"]


def test_error_answers_repeat_the_id(client):
    refused = client.get("/api/status")  # not signed in
    assert refused.status_code == 401
    assert refused.json()["request_id"] == refused.headers["X-Request-ID"]
    missing = client.get("/api/no-such-route")
    assert missing.status_code == 404
    assert missing.json()["request_id"] == missing.headers["X-Request-ID"]
    bad = client.post("/api/auth/login", json={"username": 5})
    assert bad.status_code == 422
    assert bad.json()["request_id"] == bad.headers["X-Request-ID"]


def test_a_clients_own_id_is_kept_only_when_safe(client):
    kept = client.get("/", headers={"X-Request-ID": "phone-1234abcd"})
    assert kept.headers["X-Request-ID"] == "phone-1234abcd"
    for unsafe in ("short", "has spaces in it", "semi;colon-1234", "x" * 65):
        replaced = client.get("/", headers={"X-Request-ID": unsafe})
        assert replaced.headers["X-Request-ID"] != unsafe


def test_an_unexpected_error_is_logged_with_the_id_and_hidden(config, caplog):
    from fastapi.testclient import TestClient

    from agent.main import create_app

    app = create_app(config)
    broken = APIRouter()

    @broken.get("/api/broken-for-test")
    async def boom():
        raise RuntimeError("secret internals")

    app.include_router(broken)
    caplog.handler.addFilter(RequestIdFilter())
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/broken-for-test")
    assert response.status_code == 500
    rid = response.headers["X-Request-ID"]
    body = response.json()
    assert body["request_id"] == rid
    assert "secret internals" not in response.text
    logged = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert logged and logged[-1].request_tag == f" [request {rid}]"


def test_log_lines_outside_a_request_have_no_tag():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello", None, None)
    token = requestid.current.set(None)
    try:
        RequestIdFilter().filter(record)
    finally:
        requestid.current.reset(token)
    assert record.request_tag == ""
    token = requestid.current.set("abc123def456")
    try:
        RequestIdFilter().filter(record)
    finally:
        requestid.current.reset(token)
    assert record.request_tag == " [request abc123def456]"
