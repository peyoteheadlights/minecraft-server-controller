"""The /ws live stream.

Authentication happens in the **first message**, not the query string, so the
token never lands in a proxy log or browser history:

    client -> {"type": "auth", "token": "..."}
    server -> {"type": "ready", ...}

The auth message may name the server the page is showing ("server_id");
the ready message then carries that server's status and console. Every
event carries the ``server_id`` it is about (null for the agent itself), and
the page filters to the server it shows: one connection serves every server.
Each connection owns a bounded queue; if a phone on a bad connection cannot
keep up, its oldest events are dropped rather than the agent stalling.

Client messages are actions with a declared permission (WS_ACTIONS in
agent/security/permissions.py); anything else is ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..security.auth import AuthError
from ..security.permissions import WS_ACTIONS, check

log = logging.getLogger("msc.ws")

# Event types only the page showing that server needs.
PAGE_ONLY = frozenset({"console", "metrics"})

ws_router = APIRouter()

AUTH_TIMEOUT = 10.0
HEARTBEAT = 25.0
QUEUE_SIZE = 400


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, default=str))


@ws_router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    core = getattr(ws.app.state, "core", None)
    if core is None:  # pragma: no cover
        await ws.close(code=1013)
        return

    # Same-origin check: a browser sends Origin on websocket handshakes, and
    # cross-site JS cannot forge it. This blocks a malicious page in another
    # tab from opening a socket to the agent.
    origin = ws.headers.get("origin")
    allowed = [str(o) for o in core.config.network.allowed_origins]
    if origin and allowed and origin not in allowed:
        await ws.close(code=1008)
        return

    await ws.accept()
    client_ip = ws.client.host if ws.client else "unknown"

    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT)
        message = json.loads(raw)
        if message.get("type") != "auth" or not message.get("token"):
            raise AuthError("The first message must be an auth message")
        principal = core.auth.authenticate(message["token"], source_ip=client_ip)
    except (TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        await _send(ws, {"type": "error", "message": "Authentication failed"})
        await ws.close(code=1008)
        return
    except AuthError as exc:
        await _send(ws, {"type": "error", "message": exc.message})
        await ws.close(code=1008)
        return
    except WebSocketDisconnect:
        return

    def server_for(message: dict):
        """The server a message is about; the first one if it names none."""
        return core.servers.get(str(message.get("server_id") or "")) or core.default

    selected = server_for(message)
    # The server this page shows. Console lines and metrics samples of the
    # other servers are not sent at all: a phone that falls behind drops its
    # oldest messages, and those must never push out another server's crash.
    watching = {"server_id": selected.server_id}

    def accept(event) -> bool:
        if event.type in PAGE_ONLY and event.server_id is not None:
            return event.server_id == watching["server_id"]
        return True

    queue = core.bus.queue(maxsize=QUEUE_SIZE, accept=accept)
    core.db.audit("websocket_open", user=principal.user, source_ip=client_ip)

    try:
        await _send(
            ws,
            {
                "type": "ready",
                "user": principal.user,
                "server_id": selected.server_id,
                "servers": [ctx.summary() for ctx in core.servers.values()],
                "status": selected.status(),
                "console": [line.to_dict() for line in selected.server.console.tail(200)],
                "ts": time.time(),
            },
        )

        async def pump() -> None:
            while True:
                event = await queue.get()
                # The event is nested, not spread: spreading it let the event's
                # own "type" ("console", "state", ...) overwrite "event", so the
                # dashboard never recognised a single live update.
                await _send(ws, {"type": "event", "event": event.to_dict()})

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT)
                await _send(ws, {"type": "ping", "ts": time.time()})

        async def receive() -> None:
            # The socket is read-only for control purposes: the only client
            # messages acted on are a console tail request and a status
            # request. Actions go through the authenticated REST API, which
            # audits them.
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                kind = message.get("type")
                if kind not in WS_ACTIONS:
                    continue
                try:
                    check(principal, WS_ACTIONS[kind])
                except AuthError as exc:
                    # Not "error": that one means the session ended.
                    await _send(ws, {"type": "denied", "action": kind, "message": exc.message})
                    continue
                ctx = server_for(message)
                # Asking for a named server's console or status means the page
                # now shows that server.
                if message.get("server_id") in core.servers:
                    watching["server_id"] = ctx.server_id
                if kind == "tail":
                    count = min(int(message.get("lines", 100) or 100), 500)
                    await _send(
                        ws,
                        {
                            "type": "console_tail",
                            "server_id": ctx.server_id,
                            "lines": [line.to_dict() for line in ctx.server.console.tail(count)],
                        },
                    )
                elif kind == "status":
                    await _send(
                        ws, {"type": "status", "server_id": ctx.server_id, "status": ctx.status()}
                    )

        tasks = [asyncio.create_task(t()) for t in (pump, heartbeat, receive)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for task in done:
            error = task.exception()
            if error and not isinstance(error, WebSocketDisconnect):
                log.debug("websocket task ended: %s", error)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover
        log.exception("websocket error")
    finally:
        core.bus.release(queue)
        with contextlib.suppress(Exception):
            await ws.close()
