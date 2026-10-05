"""The Overview's Recommendations card: suggested fixes for one server,
from rules over measured data (agent/recommendations.py)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import recommendations
from ...security.auth import Principal
from ...security.permissions import SERVER_VIEW, SETTINGS_EDIT, require
from ..deps import audit, get_server
from .models import RecommendationActionRequest

router = APIRouter()


async def _found(ctx) -> list[recommendations.Recommendation]:
    # Reads the mods folder, the database and the disk, so off the event loop.
    facts = await asyncio.to_thread(recommendations.gather, ctx)
    return recommendations.evaluate(facts)


@router.get("/recommendations")
async def list_recommendations(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return recommendations.visible(ctx.db, await _found(ctx))


@router.post("/recommendations/{rec_id}")
async def act_on_recommendation(
    rec_id: str,
    payload: RecommendationActionRequest,
    request: Request,
    principal: Principal = Depends(require(SETTINGS_EDIT)),
    ctx=Depends(get_server),
):
    try:
        recommendations.act(ctx.db, await _found(ctx), rec_id, payload.action)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit(ctx, request, f"recommendation_{payload.action}", target=rec_id)
    return recommendations.visible(ctx.db, await _found(ctx))
