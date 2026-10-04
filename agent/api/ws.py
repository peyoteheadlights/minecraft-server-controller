"""The /ws live stream.

Authentication happens in the **first message**, not the query string, so the
token never lands in a proxy log or browser history:

    client -> {"type": "auth", "token": "..."}
    server -> {"type": "ready", ...}

After that the server pushes console lines, state changes, metrics samples
and events. Each connection owns a bounded queue; if a phone on a bad
connection cannot keep up, its oldest events are dropped rather than the
agent stalling.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..security.auth import AuthError

log = logging.getLogger("msc.ws")

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
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        await _send(ws, {"type": "error", "message": "Authentication failed"})
        await ws.close(code=1008)
        return
    except AuthError as exc:
        await _send(ws, {"type": "error", "message": exc.message})
        await ws.close(code=1008)
        return
    except WebSocketDisconnect:
        return

    queue = core.bus.queue(maxsize=QUEUE_SIZE)
    core.db.audit("websocket_open", user=principal.user, source_ip=client_ip)

    try:
        await _send(
            ws,
            {
                "type": "ready",
                "user": principal.user,
                "status": core.status(),
                "console": [line.to_dict() for line in core.server.console.tail(200)],
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
            # messages accepted are pongs and a console tail request. Actions
            # go through the authenticated REST API, which audits them.
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if message.get("type") == "tail":
                    count = min(int(message.get("lines", 100) or 100), 500)
                    await _send(
                        ws,
                        {
                            "type": "console_tail",
                            "lines": [l.to_dict() for l in core.server.console.tail(count)],
                        },
                    )
                elif message.get("type") == "status":
                    await _send(ws, {"type": "status", "status": core.status()})

        tasks = [asyncio.create_task(t()) for t in (pump, heartbeat, receive)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.debug("websocket task ended: %s", exc)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover
        log.exception("websocket error")
    finally:
        core.bus.release(queue)
        with contextlib.suppress(Exception):
            await ws.close()
