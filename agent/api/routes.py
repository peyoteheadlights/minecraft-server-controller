"""REST API.

Every route except /api/health and /api/auth/login requires a bearer token.
No route accepts a filesystem path, a shell string or a command line: the
only free text that reaches the operating system is a Minecraft console
command, and that is validated by agent.minecraft.commands first.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..config import ConfigError
from ..minecraft.commands import CommandError, validate
from ..minecraft.state import ExitReason
from ..mods.modrinth import ModrinthError
from ..security.auth import Principal
from ..mods.dependencies import DependencyError
from .deps import audit, client_ip, get_core, require_auth
from .errors import DOMAIN_ERRORS, audit_failure, respond_as

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------
# models
# ----------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    label: str = Field(default="", max_length=80)


class CommandRequest(BaseModel):
    command: str = Field(max_length=512)
    confirm: bool = False


class StopRequest(BaseModel):
    timeout: float | None = Field(default=None, ge=1, le=1800)
    force: bool = False


class BackupRequest(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    includes: list[str] | None = None
    note: str | None = Field(default=None, max_length=300)


class RestoreRequest(BaseModel):
    confirm: bool = False
    start_after: bool = False
    safety_backup: bool = True


class ModInstallRequest(BaseModel):
    project: str = Field(max_length=100)
    version_id: str | None = Field(default=None, max_length=64)
    allow_replace: bool = False
    install_dependencies: bool = False


class ModFileRequest(BaseModel):
    filename: str = Field(max_length=180)


class ModUpdateRequest(ModFileRequest):
    version_id: str | None = Field(default=None, max_length=64)


class ModRollbackRequest(BaseModel):
    mod_id: str = Field(max_length=80)
    archive_path: str = Field(max_length=500)


class ScheduleRequest(BaseModel):
    name: str = Field(max_length=80)
    task: str = Field(max_length=32)
    kind: str = Field(max_length=16)
    expr: str = Field(max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SettingsRequest(BaseModel):
    updates: dict[str, Any]


class MaintenanceRequest(BaseModel):
    enabled: bool


# ----------------------------------------------------------------------
# health and auth
# ----------------------------------------------------------------------
@router.get("/health")
async def health(core=Depends(get_core)):
    """Unauthenticated liveness probe. Deliberately reveals nothing."""
    return {"ok": True, "agent_uptime": time.time() - core.started_at,
            "auth_configured": core.auth.configured}


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, core=Depends(get_core)):
    return core.auth.login(payload.username, payload.password,
                           source_ip=client_ip(request), label=payload.label)


@router.post("/auth/logout")
async def logout(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    core.auth.logout(principal)
    return {"ok": True}


@router.post("/auth/rotate")
async def rotate(request: Request, principal: Principal = Depends(require_auth),
                 core=Depends(get_core)):
    return core.auth.rotate(principal, source_ip=client_ip(request))


@router.get("/auth/me")
async def me(principal: Principal = Depends(require_auth)):
    return principal.to_dict()


# ----------------------------------------------------------------------
# status and server control
# ----------------------------------------------------------------------
@router.get("/status")
async def status(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return core.status()


@router.get("/info")
async def server_info(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    import platform
    import psutil
    status = core.server.status()
    storage = await core.metrics.storage()
    return {
        "server": status,
        "java": core.server.java_info.to_dict() if core.server.java_info else None,
        "java_compatibility": core.server.java_compatibility(),
        "preflight": core.server.preflight().to_dict(),
        "command": core.server.build_command(),
        "storage": storage,
        "machine": {
            "os": f"{platform.system()} {platform.release()}",
            "hostname": platform.node(),
            "cpu": platform.processor() or "unknown",
            "cpu_cores": psutil.cpu_count(logical=True),
            "ram_total_gb": psutil.virtual_memory().total / 1024**3,
            "python": platform.python_version(),
        },
        "paths": {
            "server_directory": str(core.config.server_dir),
            "data_directory": str(core.config.data_dir),
            "mods_directory": str(core.config.mods_dir),
            "backup_directory": str(core.config.backup_dir),
            "log_directory": str(core.config.log_dir),
        },
    }


@router.post("/server/start")
async def server_start(request: Request, principal: Principal = Depends(require_auth),
                       core=Depends(get_core)):
    with audit_failure(core, request, "server_start"):
        result = await core.server.start(actor=principal.user)
    audit(core, request, "server_start", detail=f"pid={result['pid']}")
    # The process was launched. That is not the same as the server being up:
    # "started successfully" is only reported once the startup line appears in
    # the console, which arrives as a server_started event.
    return {
        "result": "REQUESTED",
        "detail": "The Minecraft process was launched. Watch for the server_started event, "
                  "or poll /api/status, to find out whether startup completes.",
        "pid": result["pid"],
        "command": result["command"],
        "state": core.server.state.value,
        "startup_confirmed": core.server.startup_confirmed,
    }


@router.post("/server/stop")
async def server_stop(payload: StopRequest, request: Request,
                      principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with audit_failure(core, request, "server_stop"):
        if payload.force:
            await core.server.kill(actor=principal.user)
            result = {"graceful": False, "forced": True}
        else:
            result = await core.server.stop(actor=principal.user,
                                            reason=ExitReason.USER_STOP,
                                            timeout=payload.timeout)
    audit(core, request, "server_stop", detail=str(result))
    stopped = core.server.state.value in ("OFFLINE", "CRASHED")
    return {
        "result": "VERIFIED" if stopped else "IN_PROGRESS",
        "detail": ("The process has exited and the agent observed it."
                   if stopped else "The stop was requested but the process has not exited yet."),
        **result,
        "state": core.server.state.value,
    }


@router.post("/server/restart")
async def server_restart(request: Request, principal: Principal = Depends(require_auth),
                         core=Depends(get_core)):
    with audit_failure(core, request, "server_restart"):
        result = await core.server.restart(actor=principal.user)
    audit(core, request, "server_restart")
    online = core.server.startup_confirmed and core.server.state.value == "ONLINE"
    return {
        "result": "VERIFIED" if online else "IN_PROGRESS",
        "detail": ("The server stopped and completed startup again."
                   if online else
                   "The restart was requested. Startup has not been confirmed yet; watch for "
                   "the server_started event."),
        **result,
        "state": core.server.state.value,
        "startup_confirmed": core.server.startup_confirmed,
    }


@router.post("/server/restart-now")
async def restart_now(request: Request, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    """Skip the automatic-restart countdown and start immediately."""
    with audit_failure(core, request, "restart_now", result="refused"):
        await core.server.restart_now(actor=principal.user)
    audit(core, request, "restart_now")
    return {"result": "REQUESTED", "state": core.server.state.value,
            "detail": "The server is starting. It is online once startup completes."}


@router.post("/server/cancel-restart")
async def cancel_restart(request: Request, principal: Principal = Depends(require_auth),
                         core=Depends(get_core)):
    """Stop the automatic-restart countdown. The server stays stopped."""
    with audit_failure(core, request, "cancel_restart", result="refused"):
        await core.server.cancel_pending_restart(actor=principal.user)
    audit(core, request, "cancel_restart")
    return {"result": "VERIFIED", "state": core.server.state.value,
            "detail": "Automatic restart cancelled. The server will stay stopped."}


@router.post("/server/clear-crash-block")
async def clear_crash_block(request: Request, principal: Principal = Depends(require_auth),
                            core=Depends(get_core)):
    core.server.clear_crash_block()
    audit(core, request, "clear_crash_block")
    return {"ok": True, "auto_restart_blocked": core.server.auto_restart_blocked}


@router.post("/server/command")
async def server_command(payload: CommandRequest, request: Request,
                         principal: Principal = Depends(require_auth), core=Depends(get_core)):
    validated = validate(payload.command, confirm=payload.confirm)
    await core.server.send_command(validated.raw)
    audit(core, request, "console_command", target=validated.name, detail=validated.raw)
    return {"result": "SENT",
            "detail": "The command was written to the Minecraft console. Read the console "
                      "output to see what the server did with it.",
            **validated.to_dict()}


@router.get("/server/command/check")
async def check_command(command: str, principal: Principal = Depends(require_auth)):
    """Ask whether a command needs confirmation, before sending it."""
    from ..minecraft.commands import describe_danger
    try:
        validate(command, confirm=True)
        valid, error = True, None
    except CommandError as exc:
        valid, error = False, str(exc)
    return {"valid": valid, "error": error, "danger_reason": describe_danger(command)}


# ----------------------------------------------------------------------
# console and logs
# ----------------------------------------------------------------------
@router.get("/logs")
async def logs(lines: int = 100, since: int = 0, search: str = "", level: str = "",
               principal: Principal = Depends(require_auth), core=Depends(get_core)):
    lines = max(1, min(int(lines), 500))
    if search:
        found = core.server.console.search(search, limit=lines, level=level or None)
    elif since:
        found = core.server.console.since(since, limit=lines)
    elif level:
        found = core.server.console.by_level(level, limit=lines)
    else:
        found = core.server.console.tail(lines)
    return {
        "lines": [line.to_dict() for line in found],
        "buffered": len(core.server.console),
        "buffer_limit": core.server.console.maxlen,
    }


@router.get("/logs/download", response_class=PlainTextResponse)
async def download_logs(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    body = "\n".join(core.server.console.all_raw())
    filename = f"console-{time.strftime('%Y%m%d-%H%M%S')}.log"
    return PlainTextResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/logs/clear")
async def clear_console(request: Request, principal: Principal = Depends(require_auth),
                        core=Depends(get_core)):
    """Clears the agent's in-memory view only. Minecraft's own log files are untouched."""
    core.server.console.clear()
    audit(core, request, "console_clear")
    return {"ok": True}


@router.get("/events")
async def events(limit: int = 100, principal: Principal = Depends(require_auth),
                 core=Depends(get_core)):
    limit = max(1, min(int(limit), 500))
    rows = core.db.query(
        "SELECT * FROM events WHERE server_id = ? ORDER BY ts DESC LIMIT ?",
        (core.server.server_id, limit),
    )
    return {"events": rows}


# ----------------------------------------------------------------------
# players, performance, health
# ----------------------------------------------------------------------
@router.get("/players")
async def players(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {
        "online": core.players.online(),
        "online_count": core.players.online_count(),
        "verified": core.players.verified,
        "source": core.players.verified_source,
        "known": core.players.all_players(),
        "max_players": core.config.server.max_players,
    }


@router.get("/players/sessions")
async def player_sessions(username: str = "", limit: int = 100,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"sessions": core.players.sessions(username or None, max(1, min(limit, 500)))}


@router.get("/performance")
async def performance(hours: float = 6, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    return {
        "current": core.metrics.snapshot(),
        "history": core.metrics.history(hours=max(0.1, min(hours, 168))),
        "thresholds": core.config.thresholds.to_dict(),
        "storage": await core.metrics.storage(),
    }


@router.get("/health/server")
async def server_health(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    # online_count() returns None when the player list has not been
    # established, and the health page renders that as unknown.
    return core.metrics.health(player_count=core.players.online_count())


@router.get("/worlds")
async def worlds(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"worlds": core.backups.world_summary()}


@router.post("/worlds/save")
async def save_worlds(request: Request, principal: Principal = Depends(require_auth),
                      core=Depends(get_core)):
    await core.server.send_command("save-all flush")
    audit(core, request, "world_save")
    return {"result": "REQUESTED",
            "detail": "save-all flush was written to the server console. Minecraft does not "
                      "acknowledge it in a way the agent can verify."}


# ----------------------------------------------------------------------
# backups
# ----------------------------------------------------------------------
@router.get("/backups")
async def list_backups(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"backups": core.backups.list_backups(),
            "directory": str(core.config.backup_dir),
            "retention": {
                "daily": core.config.backups.keep_daily,
                "weekly": core.config.backups.keep_weekly,
                "monthly": core.config.backups.keep_monthly,
            }}


@router.post("/backups")
async def create_backup(payload: BackupRequest, request: Request,
                        principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with audit_failure(core, request, "backup_create"):
        result = await core.backups.create(name=payload.name, includes=payload.includes,
                                           user=principal.user, note=payload.note)
    return {"ok": True, **result}


@router.get("/backups/{backup_id}/verify")
async def verify_backup(backup_id: int, principal: Principal = Depends(require_auth),
                        core=Depends(get_core)):
    with respond_as(404):
        return core.backups.verify(backup_id)


@router.get("/backups/{backup_id}/download")
async def download_backup(backup_id: int, principal: Principal = Depends(require_auth),
                          core=Depends(get_core)):
    with respond_as(404):
        path = core.backups.path_for_download(backup_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/backups/{backup_id}/restore")
async def restore_backup(backup_id: int, payload: RestoreRequest, request: Request,
                         principal: Principal = Depends(require_auth), core=Depends(get_core)):
    if not payload.confirm:
        with respond_as(404):
            target = core.backups.get(backup_id)
        return {
            "confirmation_required": True,
            "backup": target,
            "will_happen": [
                "The Minecraft server will be stopped if it is running",
                "The backup will be verified before anything is replaced",
                "A safety backup of the current world will be created first",
                "Current folders will be moved aside, not deleted",
                "The server will start again" if payload.start_after else "The server will stay offline",
            ],
        }
    with audit_failure(core, request, "backup_restore"):
        result = await core.backups.restore(backup_id, user=principal.user,
                                            start_after=payload.start_after,
                                            safety_backup=payload.safety_backup)
    return {"ok": True, **result}


@router.delete("/backups/{backup_id}")
async def delete_backup(backup_id: int, request: Request,
                        principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(404):
        result = await core.backups.delete(backup_id, user=principal.user)
    return {"ok": True, **result}


# ----------------------------------------------------------------------
# mods
# ----------------------------------------------------------------------
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


class DependencyInstallRequest(BaseModel):
    mod_ids: list[str] | None = Field(default=None, max_length=50)


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


# ----------------------------------------------------------------------
# crashes
# ----------------------------------------------------------------------
@router.get("/crashes")
async def crashes(limit: int = 50, principal: Principal = Depends(require_auth),
                  core=Depends(get_core)):
    return {"crashes": core.crashes.list_crashes(max(1, min(limit, 200)))}


@router.get("/crashes/{crash_id}")
async def crash_detail(crash_id: int, principal: Principal = Depends(require_auth),
                       core=Depends(get_core)):
    row = core.crashes.get_crash(crash_id)
    if not row:
        raise HTTPException(status_code=404, detail="That crash record does not exist")
    return row


# ----------------------------------------------------------------------
# schedules
# ----------------------------------------------------------------------
@router.get("/schedules")
async def list_schedules(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"schedules": core.scheduler.list_schedules(), "tasks": list(core.scheduler.handlers)}


@router.post("/schedules")
async def create_schedule(payload: ScheduleRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    row = core.scheduler.add(payload.name, payload.task, payload.kind, payload.expr,
                             payload.payload, payload.enabled)
    audit(core, request, "schedule_create", target=payload.name)
    return {"ok": True, "schedule": row}


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, payload: ScheduleRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    row = core.scheduler.update(schedule_id, name=payload.name, task=payload.task,
                                kind=payload.kind, expr=payload.expr,
                                payload=payload.payload, enabled=payload.enabled)
    audit(core, request, "schedule_update", target=str(schedule_id))
    return {"ok": True, "schedule": row}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(404):
        core.scheduler.delete(schedule_id)
    audit(core, request, "schedule_delete", target=str(schedule_id))
    return {"ok": True}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule(schedule_id: int, request: Request,
                       principal: Principal = Depends(require_auth), core=Depends(get_core)):
    with respond_as(404):
        row = core.scheduler.get(schedule_id)
        result = await core.scheduler.run_task(row)
    audit(core, request, "schedule_run_now", target=row["name"])
    return {"ok": True, "result": result}


# ----------------------------------------------------------------------
# settings, notifications, security
# ----------------------------------------------------------------------
SETTABLE_PREFIXES = (
    "monitor.", "thresholds.", "notifications.events.", "notifications.discord_enabled",
    "notifications.email_enabled", "notifications.email.", "notifications.min_interval_seconds",
    "backups.keep_", "backups.include", "backups.stop_server_for_backup",
    "mods.backup_before_install", "mods.update_check_hours", "maintenance.",
    "server.max_players", "server.stop_timeout", "server.start_timeout",
    "server.autostart_minecraft", "server.jvm_args", "security.session_hours",
)


@router.get("/settings")
async def get_settings(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {
        "config": core.config.as_dict(redact_secrets=True),
        "editable": list(SETTABLE_PREFIXES),
        "secrets": {
            "discord_webhook_configured": bool(core.config.discord_webhook),
            "smtp_configured": bool(core.config.smtp_password),
            "api_token_configured": bool(core.config.api_token),
        },
    }


@router.put("/settings")
async def update_settings(payload: SettingsRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    applied, rejected = {}, {}
    for key, value in payload.updates.items():
        if not any(key == p or key.startswith(p) for p in SETTABLE_PREFIXES):
            rejected[key] = "This setting cannot be changed from the dashboard"
            continue
        previous = core.config.get(key)
        core.config.set(key, value)
        try:
            core.config.section(key.split(".", 1)[0])
        except ConfigError as exc:
            core.config.set(key, previous)
            rejected[key] = str(exc)
            continue
        applied[key] = value
    if applied:
        try:
            core.config.save()
        except OSError as exc:
            raise HTTPException(status_code=500,
                                detail=f"Settings could not be written to disk: {exc}") from exc
        audit(core, request, "settings_update", detail=", ".join(applied))
    return {"ok": True, "applied": applied, "rejected": rejected}


@router.post("/maintenance")
async def set_maintenance(payload: MaintenanceRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    result = core.set_maintenance(payload.enabled, user=principal.user)
    audit(core, request, "maintenance_mode", detail="on" if payload.enabled else "off")
    return {"ok": True, **result}


@router.post("/notifications/test")
async def test_notification(channel: str, request: Request,
                            principal: Principal = Depends(require_auth), core=Depends(get_core)):
    try:
        result = await core.notifier.test(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "notification_test", target=channel, detail=str(result["sent"]))
    return result


@router.get("/notifications/history")
async def notification_history(limit: int = 50, principal: Principal = Depends(require_auth),
                               core=Depends(get_core)):
    return {"history": core.notifier.history(max(1, min(limit, 200)))}


@router.get("/security")
async def security_overview(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {
        "agent_connected": True,
        "tls": core.metrics.certificate_status(),
        "https_enabled": core.config.tls_enabled,
        "dashboard_hostname": core.config.dashboard_hostname or None,
        "tailscale": core.metrics.tailscale_status(),
        "authentication": {
            "enabled": core.auth.configured,
            "session_hours": core.config.security.session_hours,
            "api_token_configured": bool(core.config.api_token),
        },
        "active_sessions": core.auth.active_sessions(),
        "failed_logins_24h": core.auth.failed_login_count(24),
        "bind_address": f"{core.config.network.host}:{core.config.network.port}",
    }


@router.get("/security/audit")
async def audit_log(limit: int = 100, principal: Principal = Depends(require_auth),
                    core=Depends(get_core)):
    limit = max(1, min(int(limit), 500))
    return {"entries": core.db.query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))}


@router.post("/security/revoke-sessions")
async def revoke_sessions(request: Request, principal: Principal = Depends(require_auth),
                          core=Depends(get_core)):
    count = core.auth.revoke_all()
    audit(core, request, "revoke_all_sessions", detail=str(count))
    return {"ok": True, "revoked": count}


# ----------------------------------------------------------------------
# multi-server groundwork
# ----------------------------------------------------------------------
@router.get("/servers")
async def servers(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """One entry today. The data model already keys everything by server_id,
    so a second agent can be added without a schema change."""
    rows = core.db.query("SELECT * FROM servers", ())
    for row in rows:
        row["current"] = row["id"] == core.server.server_id
        row["state"] = core.server.state.value if row["current"] else "UNKNOWN"
    return {"servers": rows}


@router.get("/security/tls")
async def tls_status(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    """Certificate facts read from disk.

    Only metadata is returned. The private key is never read into a response,
    never logged, and has no endpoint of its own - the only thing reported
    about it is whether its public half matches the certificate.
    """
    return {
        "enabled": core.config.tls_enabled,
        "certificate": core.metrics.certificate_status(),
        "hostname": core.config.dashboard_hostname or None,
        "hsts": core.config.tls.hsts,
        "http_redirect": core.config.tls.http_redirect,
        "renewal": "Run 'python -m installer.make_certs --renew' on the server PC. "
                   "Tailscale-issued certificates renew automatically.",
    }



@router.get("/system/startup")
async def windows_startup_test(principal: Principal = Depends(require_auth)):
    """Test Windows Startup.

    Reads the registered scheduled task back from Windows, compares it with
    this installation, checks for the old service and duplicate entries, and
    includes the agent's own record of its last startup. Read-only.
    """
    import asyncio
    try:
        from installer.autostart import report
    except ImportError as exc:
        raise HTTPException(status_code=500,
                            detail=f"The startup inspector could not be loaded: {exc}") from exc
    return await asyncio.to_thread(report)



# ----------------------------------------------------------------------
# TPS monitoring
# ----------------------------------------------------------------------
class TpsCommandRequest(BaseModel):
    command: str = Field(max_length=100, description='"auto", "off", or a Minecraft command')


@router.get("/tps")
async def tps_status(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return core.tps.status()


@router.post("/tps/detect")
async def tps_detect(request: Request, principal: Principal = Depends(require_auth),
                     core=Depends(get_core)):
    try:
        result = await core.tps.redetect()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(core, request, "tps_redetect")
    return result


@router.put("/tps")
async def tps_set_command(payload: TpsCommandRequest, request: Request,
                          principal: Principal = Depends(require_auth), core=Depends(get_core)):
    try:
        result = await core.tps.set_command(payload.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "tps_command_set", detail=payload.command or "off")
    return result
