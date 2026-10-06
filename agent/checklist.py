"""The getting-started checklist on a new server's Overview.

Four things worth doing once, each ticked off from something the app
measured rather than from a click on the item (house rule 1): the server is
set up, a backup has really run and checked out, somebody has really
joined, and alerts are really switched on. Pressing an item only takes you
to the page where it is done.

The card can be dismissed, which is remembered per server. Once every item
is done it is finished and does not come back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import ServerContext

STATE_KEY = "getting_started"


def _server_ready(ctx: ServerContext) -> dict[str, Any]:
    """Done once this server could actually be launched: its folder is
    there and its software (a jar, or Forge's start file) is in place."""
    problem = ctx.server.launch_problem()
    return {
        "id": "server_ready",
        "done": problem is None,
        "page": "settings",
        "evidence_key": "ready" if problem is None else "not_ready",
        "evidence": {"folder": str(ctx.config.server_dir), "problem": problem},
    }


def _backup_taken(ctx: ServerContext) -> dict[str, Any]:
    good = [b for b in ctx.backups.list_backups() if b.get("status") == "ok"]
    newest = good[0] if good else None
    return {
        "id": "backup_taken",
        "done": bool(newest),
        "page": "backups",
        "evidence_key": "backup_done" if newest else "backup_none",
        "evidence": {
            "name": newest["name"] if newest else None,
            "created_at": newest["created_at"] if newest else None,
        },
    }


def _friend_joined(ctx: ServerContext) -> dict[str, Any]:
    players = ctx.players.all_players(limit=5)
    return {
        "id": "friend_joined",
        "done": bool(players),
        "page": "dashboard",
        "evidence_key": "friend_done" if players else "friend_none",
        "evidence": {"count": len(players), "name": players[0]["username"] if players else None},
    }


def _alerts_on(ctx: ServerContext) -> dict[str, Any]:
    notifications = ctx.core.config.notifications
    channels = [
        name
        for name, on in (
            ("discord", notifications.discord_enabled),
            ("email", notifications.email_enabled),
            ("push", notifications.push_enabled),
        )
        if on
    ]
    return {
        "id": "alerts_on",
        "done": bool(channels),
        "page": "app-settings",
        "evidence_key": "alerts_done" if channels else "alerts_none",
        "evidence": {"channels": channels},
    }


ITEMS = (_server_ready, _backup_taken, _friend_joined, _alerts_on)


def status(ctx: ServerContext) -> dict[str, Any]:
    items = [check(ctx) for check in ITEMS]
    done = [i for i in items if i["done"]]
    finished = len(done) == len(items)
    saved = ctx.db.get_setting(STATE_KEY, {}) or {}
    if finished and not saved.get("finished"):
        # Remembered, so the card does not come back if an item later stops
        # being true (alerts switched off again, say).
        ctx.db.set_setting(STATE_KEY, {**saved, "finished": True})
        saved = {**saved, "finished": True}
    return {
        "items": items,
        "done": len(done),
        "total": len(items),
        "show": not saved.get("dismissed") and not saved.get("finished"),
        "dismissed": bool(saved.get("dismissed")),
        "finished": bool(saved.get("finished")),
    }


def dismiss(ctx: ServerContext) -> dict[str, Any]:
    saved = ctx.db.get_setting(STATE_KEY, {}) or {}
    ctx.db.set_setting(STATE_KEY, {**saved, "dismissed": True})
    return status(ctx)
