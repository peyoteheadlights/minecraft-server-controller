"""Installed mods, Modrinth search and install, updates, rollback and
dependencies."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ...mods.dependencies import DependencyError
from ...mods.modrinth import ModrinthError
from ...security.auth import Principal
from ..deps import audit, get_core, require_auth
from ..errors import DOMAIN_ERRORS, audit_failure, respond_as
from .models import ModInstallRequest, ModFileRequest, ModUpdateRequest, ModRollbackRequest, DependencyInstallRequest

router = APIRouter()


@router.get("/mods")
async def list_mods(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    mods = core.mods.list_installed()
    checks = core.mods.check_all()
    return {
        "mods": mods,
        "problems": checks["problems"],
        "claim": checks["claim"],
        "claim_note": checks["claim_note"],
        "limitations": checks["limitations"],
        "minecraft_version": checks["minecraft_version"],
        "fabric_loader": checks["fabric_loader"],
        "directory": str(core.config.mods_dir),
        "server_state": core.server.state.value,
        "updates_checked_at": core.db.get_setting("mod_updates_checked_at"),
    }


@router.get("/mods/search")
async def search_mods(q: str = "", minecraft_version: str = "", limit: int = 20, offset: int = 0,
                      principal: Principal = Depends(require_auth), core=Depends(get_core)):
    version = minecraft_version or core.server.mc_version
    return await core.mods.modrinth.search(q, minecraft_version=version or None,
                                           limit=limit, offset=offset)


@router.get("/mods/project/{project}")
async def mod_project(project: str, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    info = await core.mods.modrinth.project(project)
    versions = await core.mods.modrinth.versions(project, core.server.mc_version)
    return {"project": info, "versions": versions[:25],
            "installed": core.mods.preview_install(info["slug"])}


@router.post("/mods/install")
async def install_mod(payload: ModInstallRequest, request: Request,
                      principal: Principal = Depends(require_auth), core=Depends(get_core)):
    try:
        result = await core.mods.install_from_modrinth(
            payload.project, user=principal.user, version_id=payload.version_id,
            allow_replace=payload.allow_replace,
            install_dependencies=payload.install_dependencies,
        )
    except DOMAIN_ERRORS as exc:
        audit(core, request, "mod_install", target=payload.project, result="failed", detail=str(exc))
        core.mods.record("install", principal.user, mod_id=payload.project,
                         result="failed", detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "mod_install", target=payload.project,
          detail=result["installed"]["version"])
    return {"ok": True, **result}


@router.post("/mods/upload")
async def upload_mod(request: Request, file: UploadFile = File(...),
                     principal: Principal = Depends(require_auth), core=Depends(get_core)):
    data = await file.read(320 * 1024 * 1024)
    with audit_failure(core, request, "mod_upload", target=file.filename):
        result = await core.mods.install_local_file(file.filename or "", data, user=principal.user)
    audit(core, request, "mod_upload", target=file.filename)
    return {"ok": True, **result}


@router.get("/mods/impact")
async def mod_impact(filename: str, principal: Principal = Depends(require_auth),
                     core=Depends(get_core)):
    with respond_as(404):
        return core.mods.removal_impact(filename)


@router.post("/mods/remove")
async def remove_mod(payload: ModFileRequest, request: Request,
                     principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with audit_failure(core, request, "mod_remove", target=payload.filename):
        result = await core.mods.remove(payload.filename, user=principal.user)
    audit(core, request, "mod_remove", target=payload.filename)
    return {"ok": True, **result}


@router.post("/mods/enable")
async def enable_mod(payload: ModFileRequest, request: Request,
                     principal: Principal = Depends(require_auth), core=Depends(get_core)):
    result = await core.mods.set_enabled(payload.filename, True, user=principal.user)
    audit(core, request, "mod_enable", target=payload.filename)
    return {"ok": True, **result}


@router.post("/mods/disable")
async def disable_mod(payload: ModFileRequest, request: Request,
                      principal: Principal = Depends(require_auth), core=Depends(get_core)):
    result = await core.mods.set_enabled(payload.filename, False, user=principal.user)
    audit(core, request, "mod_disable", target=payload.filename)
    return {"ok": True, **result}


@router.get("/mods/updates")
async def mod_updates(refresh: bool = False, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    if refresh:
        updates = await core.mods.check_updates()
        return {"updates": updates, "checked_at": time.time()}
    updates = []
    for mod in core.mods.scan():
        entry = core.db.get_setting(f"mod_update:{mod.mod_id}")
        if entry and entry.get("installed_version") == mod.version:
            updates.append(entry)
    return {"updates": updates, "checked_at": core.db.get_setting("mod_updates_checked_at")}


@router.post("/mods/update")
async def update_mod(payload: ModUpdateRequest, request: Request,
                     principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(400), audit_failure(core, request, "mod_update", target=payload.filename):
        result = await core.mods.update(payload.filename, user=principal.user,
                                        version_id=payload.version_id)
    audit(core, request, "mod_update", target=payload.filename)
    return {"ok": True, **result}


@router.get("/mods/versions/{mod_id}")
async def mod_versions(mod_id: str, principal: Principal = Depends(require_auth),
                       core=Depends(get_core)):
    return {"versions": core.mods.versions_for(mod_id)}


@router.post("/mods/rollback")
async def rollback_mod(payload: ModRollbackRequest, request: Request,
                       principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with audit_failure(core, request, "mod_rollback", target=payload.mod_id):
        result = await core.mods.rollback(payload.mod_id, payload.archive_path, user=principal.user)
    audit(core, request, "mod_rollback", target=payload.mod_id)
    return {"ok": True, **result}


@router.get("/mods/history")
async def mod_history(limit: int = 100, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    return {"history": core.mods.history(max(1, min(limit, 500)))}


@router.get("/mods/dependencies")
async def mod_dependencies(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """Every declared dependency, with readable names, ranges and status."""
    report = core.mods.deps.analyse()
    try:
        await core.mods.deps.describe(report)
    except (ModrinthError, DependencyError) as exc:
        report["lookup_error"] = f"Mod names could not be looked up on Modrinth: {exc}"
    return report


@router.post("/mods/dependencies/plan")
async def plan_dependencies(payload: DependencyInstallRequest,
                            principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """What would be downloaded, including dependencies of dependencies. Downloads nothing."""
    return await core.mods.deps.plan(payload.mod_ids)


@router.post("/mods/dependencies/install")
async def install_dependencies(payload: DependencyInstallRequest, request: Request,
                               principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with audit_failure(core, request, "dependencies_install"):
        result = await core.mods.deps.install(payload.mod_ids, user=principal.user)
    installed = [r["title"] for r in result["results"] if r["result"] == "installed"]
    audit(core, request, "dependencies_install", detail=", ".join(installed) or "nothing installed")
    return result


@router.get("/mods/check")
async def mod_check(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return core.mods.check_all()

