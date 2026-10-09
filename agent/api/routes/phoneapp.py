"""What the phone app (mobile/) reads that the dashboard doesn't: the
alerts the agent sent, for the app's Notifications tab.

The app has no Google or Apple push, so it shows new alerts live while
open and catches up from this list when it opens again. They are the same
alerts as everywhere else (``notifications.*`` decides which events send
one and how often), kept whether or not any other channel is turned on.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...security.auth import Principal
from ...security.permissions import SERVER_VIEW, can_see_server, require
from ..deps import get_core
from ..responses import AppAlerts

router = APIRouter()


@router.get("/alerts", response_model=AppAlerts)
async def alerts(
    after: int | None = Query(None, ge=0, description="Only alerts newer than this id"),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require(SERVER_VIEW)),
    core=Depends(get_core),
):
    """Alerts newer than ``after``, oldest first.

    A helper sees only the servers they may use; alerts about the PC itself
    (failed sign-ins, the certificate, the PC's memory) are the owner's.
    Without ``after`` nothing old is returned, only where the list is now,
    so a newly paired phone doesn't replay old alerts.
    """
    latest_row = core.db.query_one("SELECT MAX(id) AS id FROM app_alerts")
    latest = int(latest_row["id"] or 0) if latest_row else 0
    rows: list[dict] = []
    if after is not None:
        found = core.db.query(
            "SELECT * FROM app_alerts WHERE id > ? ORDER BY id LIMIT ?",
            (after, limit),
        )
        for row in found:
            if row["server_id"] is None:
                if not principal.is_owner:
                    continue
            elif not can_see_server(principal, row["server_id"]):
                continue
            rows.append(row)
        if len(found) == limit:
            # More are waiting: the next read carries on after the last one.
            latest = found[-1]["id"]
    return {
        "alerts": rows,
        "latest": latest,
        "enabled": core.config.notifications.push_enabled,
    }
