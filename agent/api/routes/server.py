"""Server status and control: start, stop, restart, console commands,
performance, health, worlds and TPS monitoring."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ...minecraft.commands import CommandError, validate
from ...minecraft.state import ExitReason
from ...security.auth import Principal
from ..deps import audit, get_core, require_auth
from ..errors import audit_failure
from .models import CommandRequest, StopRequest, TpsCommandRequest

router = APIRouter()


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
async def server_start(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
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
async def server_stop(
    payload: StopRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
    core=Depends(get_core),
):
    with audit_failure(core, request, "server_stop"):
        if payload.force:
            await core.server.kill(actor=principal.user)
            result = {"graceful": False, "forced": True}
        else:
            result = await core.server.stop(
                actor=principal.user, reason=ExitReason.USER_STOP, timeout=payload.timeout
            )
    audit(core, request, "server_stop", detail=str(result))
    stopped = core.server.state.value in ("OFFLINE", "CRASHED")
    return {
        "result": "VERIFIED" if stopped else "IN_PROGRESS",
        "detail": (
            "The process has exited and the agent observed it."
            if stopped
            else "The stop was requested but the process has not exited yet."
        ),
        **result,
        "state": core.server.state.value,
    }


@router.post("/server/restart")
async def server_restart(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    with audit_failure(core, request, "server_restart"):
        result = await core.server.restart(actor=principal.user)
    audit(core, request, "server_restart")
    online = core.server.startup_confirmed and core.server.state.value == "ONLINE"
    return {
        "result": "VERIFIED" if online else "IN_PROGRESS",
        "detail": (
            "The server stopped and completed startup again."
            if online
            else "The restart was requested. Startup has not been confirmed yet; watch for "
            "the server_started event."
        ),
        **result,
        "state": core.server.state.value,
        "startup_confirmed": core.server.startup_confirmed,
    }


@router.post("/server/restart-now")
async def restart_now(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    """Skip the automatic-restart countdown and start immediately."""
    with audit_failure(core, request, "restart_now", result="refused"):
        await core.server.restart_now(actor=principal.user)
    audit(core, request, "restart_now")
    return {
        "result": "REQUESTED",
        "state": core.server.state.value,
        "detail": "The server is starting. It is online once startup completes.",
    }


@router.post("/server/cancel-restart")
async def cancel_restart(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    """Stop the automatic-restart countdown. The server stays stopped."""
    with audit_failure(core, request, "cancel_restart", result="refused"):
        await core.server.cancel_pending_restart(actor=principal.user)
    audit(core, request, "cancel_restart")
    return {
        "result": "VERIFIED",
        "state": core.server.state.value,
        "detail": "Automatic restart cancelled. The server will stay stopped.",
    }


@router.post("/server/clear-crash-block")
async def clear_crash_block(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    core.server.clear_crash_block()
    audit(core, request, "clear_crash_block")
    return {"ok": True, "auto_restart_blocked": core.server.auto_restart_blocked}


@router.post("/server/command")
async def server_command(
    payload: CommandRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
    core=Depends(get_core),
):
    validated = validate(payload.command, confirm=payload.confirm)
    await core.server.send_command(validated.raw)
    audit(core, request, "console_command", target=validated.name, detail=validated.raw)
    return {
        "result": "SENT",
        "detail": "The command was written to the Minecraft console. Read the console "
        "output to see what the server did with it.",
        **validated.to_dict(),
    }


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


@router.get("/performance")
async def performance(
    hours: float = 6, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
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
    # The checks include `tailscale status` and a TCP connect, so they run
    # in a worker thread.
    return await asyncio.to_thread(core.metrics.health, player_count=core.players.online_count())


@router.get("/worlds")
async def worlds(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return {"worlds": core.backups.world_summary()}


@router.post("/worlds/save")
async def save_worlds(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    await core.server.send_command("save-all flush")
    audit(core, request, "world_save")
    return {
        "result": "REQUESTED",
        "detail": "save-all flush was written to the server console. Minecraft does not "
        "acknowledge it in a way the agent can verify.",
    }


@router.get("/tps")
async def tps_status(principal: Principal = Depends(require_auth), core=Depends(get_core)):
    return core.tps.status()


@router.post("/tps/detect")
async def tps_detect(
    request: Request, principal: Principal = Depends(require_auth), core=Depends(get_core)
):
    try:
        result = await core.tps.redetect()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(core, request, "tps_redetect")
    return result


@router.put("/tps")
async def tps_set_command(
    payload: TpsCommandRequest,
    request: Request,
    principal: Principal = Depends(require_auth),
    core=Depends(get_core),
):
    try:
        result = await core.tps.set_command(payload.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(core, request, "tps_command_set", detail=payload.command or "off")
    return result
