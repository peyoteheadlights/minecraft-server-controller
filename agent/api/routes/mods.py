"""Installed mods, Modrinth search and install, updates, rollback and
dependencies."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ...jobs import JobConflict
from ...mods.dependencies import DependencyError
from ...mods.modrinth import ModrinthError
from ...security.auth import Principal
from ...security.permissions import MODS_MANAGE, SERVER_VIEW, require
from ..deps import audit, get_server
from ..errors import DOMAIN_ERRORS, audit_failure, respond_as
from .models import (
    DependencyInstallRequest,
    ModFileRequest,
    ModInstallRequest,
    ModRollbackRequest,
    ModUpdateRequest,
)

router = APIRouter()


@router.get("/mods")
async def list_mods(principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)):
    mods = ctx.mods.list_installed()
    checks = ctx.mods.check_all()
    return {
        "mods": mods,
        "problems": checks["problems"],
        "claim": checks["claim"],
        "claim_note": checks["claim_note"],
        "limitations": checks["limitations"],
        "minecraft_version": checks["minecraft_version"],
        "fabric_loader": checks["fabric_loader"],
        "directory": str(ctx.config.mods_dir),
        "server_state": ctx.server.state.value,
        "updates_checked_at": ctx.db.get_setting("mod_updates_checked_at"),
    }


@router.get("/mods/search")
async def search_mods(
    q: str = "",
    minecraft_version: str = "",
    limit: int = 20,
    offset: int = 0,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    version = minecraft_version or ctx.server.mc_version
    return await ctx.mods.modrinth.search(
        q, minecraft_version=version or None, limit=limit, offset=offset
    )


@router.get("/mods/project/{project}")
async def mod_project(
    project: str, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    info = await ctx.mods.modrinth.project(project)
    versions = await ctx.mods.modrinth.versions(project, ctx.server.mc_version)
    return {
        "project": info,
        "versions": versions[:25],
        "installed": ctx.mods.preview_install(info["slug"]),
    }


@router.post("/mods/install")
async def install_mod(
    payload: ModInstallRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    try:
        result = await ctx.mod_change(
            f"Installing {payload.project}",
            lambda: ctx.mods.install_from_modrinth(
                payload.project,
                user=principal.user,
                version_id=payload.version_id,
                allow_replace=payload.allow_replace,
                install_dependencies=payload.install_dependencies,
            ),
            principal.user,
        )
    except JobConflict:
        raise
    except DOMAIN_ERRORS as exc:
        audit(ctx, request, "mod_install", target=payload.project, result="failed", detail=str(exc))
        ctx.mods.record(
            "install", principal.user, mod_id=payload.project, result="failed", detail=str(exc)
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(
        ctx, request, "mod_install", target=payload.project, detail=result["installed"]["version"]
    )
    return {"ok": True, **result}


@router.post("/mods/upload")
async def upload_mod(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    data = await file.read(320 * 1024 * 1024)
    with audit_failure(ctx, request, "mod_upload", target=file.filename):
        result = await ctx.mod_change(
            f"Adding {file.filename}",
            lambda: ctx.mods.install_local_file(file.filename or "", data, user=principal.user),
            principal.user,
        )
    audit(ctx, request, "mod_upload", target=file.filename)
    return {"ok": True, **result}


@router.get("/mods/impact")
async def mod_impact(
    filename: str, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    with respond_as(404):
        return ctx.mods.removal_impact(filename)


@router.post("/mods/remove")
async def remove_mod(
    payload: ModFileRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    with audit_failure(ctx, request, "mod_remove", target=payload.filename):
        result = await ctx.mod_change(
            f"Removing {payload.filename}",
            lambda: ctx.mods.remove(payload.filename, user=principal.user),
            principal.user,
        )
    audit(ctx, request, "mod_remove", target=payload.filename)
    return {"ok": True, **result}


@router.post("/mods/enable")
async def enable_mod(
    payload: ModFileRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    result = await ctx.mod_change(
        f"Turning on {payload.filename}",
        lambda: ctx.mods.set_enabled(payload.filename, True, user=principal.user),
        principal.user,
    )
    audit(ctx, request, "mod_enable", target=payload.filename)
    return {"ok": True, **result}


@router.post("/mods/disable")
async def disable_mod(
    payload: ModFileRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    result = await ctx.mod_change(
        f"Turning off {payload.filename}",
        lambda: ctx.mods.set_enabled(payload.filename, False, user=principal.user),
        principal.user,
    )
    audit(ctx, request, "mod_disable", target=payload.filename)
    return {"ok": True, **result}


@router.get("/mods/updates")
async def mod_updates(
    refresh: bool = False,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    if refresh:
        updates = await ctx.mods.check_updates()
        return {"updates": updates, "checked_at": time.time()}
    updates = []
    for mod in ctx.mods.scan():
        entry = ctx.db.get_setting(f"mod_update:{mod.mod_id}")
        if entry and entry.get("installed_version") == mod.version:
            updates.append(entry)
    return {"updates": updates, "checked_at": ctx.db.get_setting("mod_updates_checked_at")}


@router.post("/mods/update")
async def update_mod(
    payload: ModUpdateRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    with respond_as(400), audit_failure(ctx, request, "mod_update", target=payload.filename):
        result = await ctx.mod_change(
            f"Updating {payload.filename}",
            lambda: ctx.mods.update(
                payload.filename, user=principal.user, version_id=payload.version_id
            ),
            principal.user,
        )
    audit(ctx, request, "mod_update", target=payload.filename)
    return {"ok": True, **result}


@router.get("/mods/versions/{mod_id}")
async def mod_versions(
    mod_id: str, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return {"versions": ctx.mods.versions_for(mod_id)}


@router.post("/mods/rollback")
async def rollback_mod(
    payload: ModRollbackRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    with audit_failure(ctx, request, "mod_rollback", target=payload.mod_id):
        result = await ctx.mod_change(
            f"Rolling back {payload.mod_id}",
            lambda: ctx.mods.rollback(payload.mod_id, payload.archive_path, user=principal.user),
            principal.user,
        )
    audit(ctx, request, "mod_rollback", target=payload.mod_id)
    return {"ok": True, **result}


@router.get("/mods/history")
async def mod_history(
    limit: int = 100, principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    return {"history": ctx.mods.history(max(1, min(limit, 500)))}


@router.get("/mods/dependencies")
async def mod_dependencies(
    principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)
):
    """Every declared dependency, with readable names, ranges and status."""
    report = ctx.mods.deps.analyse()
    try:
        await ctx.mods.deps.describe(report)
    except (ModrinthError, DependencyError) as exc:
        report["lookup_error"] = f"Mod names could not be looked up on Modrinth: {exc}"
    return report


@router.post("/mods/dependencies/plan")
async def plan_dependencies(
    payload: DependencyInstallRequest,
    principal: Principal = Depends(require(SERVER_VIEW)),
    ctx=Depends(get_server),
):
    """What would be downloaded, including dependencies of dependencies. Downloads nothing."""
    return await ctx.mods.deps.plan(payload.mod_ids)


@router.post("/mods/dependencies/install")
async def install_dependencies(
    payload: DependencyInstallRequest,
    request: Request,
    principal: Principal = Depends(require(MODS_MANAGE)),
    ctx=Depends(get_server),
):
    with audit_failure(ctx, request, "dependencies_install"):
        result = await ctx.mod_change(
            "Installing dependencies",
            lambda: ctx.mods.deps.install(payload.mod_ids, user=principal.user),
            principal.user,
        )
    installed = [r["title"] for r in result["results"] if r["result"] == "installed"]
    audit(ctx, request, "dependencies_install", detail=", ".join(installed) or "nothing installed")
    return result


@router.get("/mods/check")
async def mod_check(principal: Principal = Depends(require(SERVER_VIEW)), ctx=Depends(get_server)):
    return ctx.mods.check_all()
