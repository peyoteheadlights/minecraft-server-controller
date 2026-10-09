"""The Minecraft process supervisor.

Responsibilities:

* launch the server as a real child process - argv list, **never** a
  shell, fixed working directory. Most types run
  ``java -Xmx6G -jar <jar> nogui``; Forge and NeoForge run
  ``java -Xmx6G @libraries/.../win_args.txt nogui`` from the argument file
  their installer wrote (``server.args_file``); Bedrock runs its own
  ``bedrock_server.exe`` from the server folder, with no arguments
* stream its console into a bounded buffer
* write validated Minecraft commands to its stdin
* tell the difference between a graceful stop, a clean self-shutdown, a
  startup failure and a crash
* restart after a crash, with crash-loop protection

The supervisor stays alive when Minecraft dies. That is the whole point.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..events import Event, EventBus
from . import cpu
from .console import ConsoleBuffer, ConsoleLine, extract_signals
from .state import NORMAL_REASONS, ExitReason, ServerState

if TYPE_CHECKING:
    from .java import JavaInfo

log = logging.getLogger("msc.process")


# The only programs a Bedrock server is launched as (house rule 2).
EXE_NAMES = frozenset({"bedrock_server.exe", "bedrock_server"})


class ServerError(RuntimeError):
    """Operator-visible problem (missing jar, java, wrong state, ...)."""


class PreflightResult:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems, "warnings": self.warnings}


class MinecraftServer:
    def __init__(self, config, bus: EventBus, db=None):
        self.config = config
        self.bus = bus
        self.db = db
        self.server_id: str = config.server.id

        self.console = ConsoleBuffer(maxlen=2000)
        # UNKNOWN until verify_state() has actually looked. The agent has
        # not checked anything yet, and reporting OFFLINE here would be a
        # guess that happens to be right most of the time.
        self.state: ServerState = ServerState.UNKNOWN
        self.state_verified_at: float | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.pid: int | None = None

        self.started_at: float | None = None
        self.online_at: float | None = None
        self.startup_seconds: float | None = None
        self.last_exit_code: int | None = None
        self.last_exit_reason: ExitReason | None = None
        self.last_state_change: float = time.time()

        self.mc_version: str | None = None
        self.loader_version: str | None = None
        # The loader the console named ("Paper", "Fabric Loader"), and the
        # type that implies, so a wrongly set type can be reported. Never
        # used to change the configured type by itself.
        self.loader_name: str | None = None
        self.detected_type: str | None = None
        # The version the app is installing or has just installed, shown as
        # "pending" until the console reports the new version.
        self.pending_version: dict[str, Any] | None = None
        self.eula_required = False
        self.java_version: str | None = None
        self.detected_port: int | None = None
        self.mod_count: int | None = None

        self.tps: float | None = None
        self.mspt: float | None = None
        self.tps_updated: float | None = None
        # Which provider actually answered. None means nothing has, and the
        # dashboard must show 'unknown' rather than a plausible 20.0.
        self.tps_source: str | None = None
        self.tps_status: dict | None = None  # published by TpsMonitor
        self._target_tps: float | None = None  # vanilla's configured rate, not a measurement
        self.tps_asked_at: float | None = None
        self.java_info: JavaInfo | None = None
        self.startup_confirmed = False  # True only after 'Done (..)!' was seen

        self._stop_requested = False
        self._stop_reason: ExitReason = ExitReason.UNKNOWN
        self._restart_after_stop = False
        self._reader_task: asyncio.Task | None = None
        self._waiter_task: asyncio.Task | None = None
        self._restart_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._online_event = asyncio.Event()
        self._exited_event = asyncio.Event()
        self._exited_event.set()

        self._crash_times: deque[float] = deque(maxlen=50)
        # automatic-restart countdown; restart_at is the authoritative deadline
        self.restart_at: float | None = None
        self.restart_delay: float | None = None
        self.auto_restart_cancelled = False
        self._restart_sleeping = False  # True only while the countdown is waiting
        self.auto_restart_blocked = False
        self.auto_restart_block_reason: str | None = None

        self.signal_hook: Callable[..., Awaitable[Any]] | None = None  # PlayerTracker / metrics
        self.crash_hook: Callable[..., Awaitable[Any]] | None = None  # CrashReporter
        # Set by the agent when it manages several servers: reasons this one
        # must not start now (another running server holds its port or
        # folder), and things worth a warning (the port looks busy).
        self.start_guard: Callable[[], list[str]] | None = None
        self.start_warnings: Callable[[], list[str]] | None = None
        # Set by the safe-change routine while it has stopped the server to
        # change its files (a restore, for example): starting then would load
        # a half-changed world, so every start is refused until it clears.
        self.held_by: str | None = None
        self.maintenance = False
        # True when auto-sleep stopped this server because nobody was
        # playing, so the dashboard can say why it is off. Cleared on start.
        self.stopped_for_sleep = False

    # ------------------------------------------------------------------
    # info
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def uptime(self) -> float | None:
        if self.started_at and self.state in (
            ServerState.ONLINE,
            ServerState.STOPPING,
            ServerState.STARTING,
        ):
            return time.time() - self.started_at
        return None

    def _state_source(self) -> str:
        """Where the current state value came from. Source of truth, recorded
        so the dashboard never has to guess how much to trust it."""
        if self.state is ServerState.UNKNOWN:
            return "not checked"
        if self.state is ServerState.ONLINE:
            return "process running + startup line detected in console"
        if self.state in (ServerState.STARTING, ServerState.STOPPING, ServerState.RESTARTING):
            return "process running, transition in progress"
        return "process exit observed by the agent"

    @property
    def tps_candidates(self) -> tuple[str, ...]:
        """The TPS commands this server's type answers, in order."""
        return self.config.server_type.tps_commands

    def tps_unavailable_reason(self) -> str | None:
        """Why TPS is unknown, or None when it is actually known."""
        if self.tps is not None:
            return None
        if self.state is not ServerState.ONLINE:
            return "The server is not online, so no tick rate can be measured."
        status = getattr(self, "tps_status", None)
        if status:
            if status.get("state") == "detecting":
                return "Checking which TPS command this server supports…"
            if status.get("state") in ("unavailable", "disabled"):
                return status.get("message")
            if status.get("state") == "active":
                return f"Waiting for the first reading from '{status.get('command')}'."
        command = self.config.monitor.tps_command.strip()
        if command.lower() == "auto":
            return "No TPS command has been detected yet."
        if not command or command.lower() == "off":
            return "No tick-rate command is configured (monitor.tps_command is empty)."
        if self.tps_asked_at is None:
            return f"The agent has not yet asked for the tick rate ('{command}')."
        return (
            f"'{command}' was sent but nothing answered with a tick rate. "
            f"A {self.config.server_type.name} server may need the spark mod for this, "
            "or Minecraft 1.20.3 and newer answer 'tick query'."
        )

    def verify_state(self) -> ServerState:
        """Check the operating system, not our own memory.

        Called at agent startup so the very first state the dashboard sees has
        actually been verified rather than assumed.
        """
        if self.process is not None and self.process.returncode is None:
            # a child we launched and are still tracking
            self.state_verified_at = time.time()
            return self.state
        if self.state in (ServerState.CRASHED, ServerState.RESTART_PENDING):
            self.state_verified_at = time.time()
            return self.state
        self.state = ServerState.OFFLINE
        self.state_verified_at = time.time()
        return self.state

    def detect_java(self):
        """Detect the Java runtime. Source of truth: `java -version` output."""
        from .java import detect_java as _detect

        self.java_info = _detect(self.config.server.java)
        self.java_version = self.java_info.version_string
        return self.java_info

    def java_compatibility(self) -> dict[str, Any] | None:
        from .java import check_compatibility

        if not self.java_info or not self.config.server_type.needs_java:
            return None
        return check_compatibility(self.java_info, self.mc_version)

    def eula_not_accepted(self) -> bool:
        """True when this server's eula.txt is there and doesn't say
        eula=true. A missing file is not a refusal: Minecraft writes it."""
        if not self.config.server_dir_configured:
            return False
        eula = self.config.server_dir / "eula.txt"
        try:
            lines = eula.read_text(encoding="utf-8", errors="replace").lower().splitlines()
        except OSError:
            return False
        return not any(line.strip().replace(" ", "") == "eula=true" for line in lines)

    def build_command(self) -> list[str]:
        """The launch command, from configuration only. Forge and NeoForge
        are launched from the argument file their installer wrote."""
        raw = self.config.server.raw_command
        if raw:
            return [str(x) for x in raw]
        if self.config.server_type.launch == "exe":
            # Bedrock: the program the app unpacked, by its full path inside
            # the server folder (checked in preflight). No Java, no memory
            # flags and no arguments: it reads server.properties itself.
            return [str(self.config.server_dir / self.config.server.jar)]
        java = self.config.server.java
        jvm = [str(a) for a in self.config.server.jvm_args]
        jvm += cpu.jvm_args(self.config.server.cpu_cores, jvm)
        args = [str(a) for a in self.config.server.server_args]
        args_file = self.config.server.args_file.strip()
        if self.config.server_type.launch == "args_file" and args_file:
            # The path is written by the installer this app ran, and is
            # always inside the server folder (checked in preflight).
            return [java, *jvm, f"@{args_file}", *args]
        return [java, *jvm, "-jar", self.config.server.jar, *args]

    def launch_problem(self) -> str | None:
        """Why this server cannot be launched as configured, or None. Forge
        and NeoForge need their argument file; the others need their jar."""
        from ..security.paths import is_inside

        directory = self.config.server_dir
        server_type = self.config.server_type
        if server_type.launch == "args_file":
            relative = self.config.server.args_file.strip()
            if not relative:
                return (
                    f"This {server_type.name} server hasn't been set up yet. Use Change "
                    "version in Server settings to install it."
                )
            path = (directory / relative).resolve()
            if not is_inside(directory, path):
                return "The server's start file isn't inside its own folder, so it wasn't used."
            if not path.is_file():
                return (
                    f"{server_type.name}'s start file is missing: {path}. Reinstall this "
                    "version from Server settings."
                )
            return None
        jar = directory / self.config.server.jar
        if server_type.launch == "exe":
            name = self.config.server.jar.strip()
            if name not in EXE_NAMES or not is_inside(directory, jar.resolve()):
                # Only Mojang's own program, by its own name, from the
                # server's own folder (docs/security.md).
                return (
                    "The server's program isn't Bedrock's own (bedrock_server.exe) inside "
                    "the server's folder, so it wasn't started."
                )
            if not jar.is_file():
                return (
                    f"The {server_type.name} server program isn't there: {jar}. Install it "
                    "again from Server settings."
                )
            return None
        if not jar.is_file():
            return f"The server file isn't there: {jar}"
        return None

    def preflight(self) -> PreflightResult:
        result = PreflightResult()
        if self.held_by:
            result.problems.append(
                f"Wait for '{self.held_by}' to finish first. The server's files are being "
                "changed, so it cannot start until that is done."
            )
            return result
        if not self.config.server_dir_configured:
            result.problems.append(
                "The Minecraft server folder is not set. Open config/config.yaml and set "
                "server.directory to the folder that contains your server jar."
            )
            return result
        directory = self.config.server_dir
        if not directory.is_dir():
            result.problems.append(f"The server's folder isn't there: {directory}")
            return result
        if not self.config.server.raw_command:
            problem = self.launch_problem()
            if problem:
                result.problems.append(problem)
            java = self.config.server.java
            if not self.config.server_type.needs_java:
                pass
            elif not (Path(java).is_file() or shutil.which(java)):
                result.problems.append(f"Java isn't installed on this PC (looked for {java}).")
            else:
                # Detect the runtime and compare it against the Minecraft
                # version we have actually observed. An unknown result is a
                # warning, never a silent pass and never a block.
                info = self.java_info or self.detect_java()
                verdict = self.java_compatibility() or {}
                if verdict.get("verdict") == "incompatible":
                    result.problems.append(verdict["detail"])
                elif verdict.get("verdict") == "unknown" and info.version_major is None:
                    result.warnings.append(
                        "The installed Java version could not be detected, so compatibility "
                        "with Minecraft could not be checked."
                    )
        cores = self.config.server.cpu_cores
        if cores:
            result.problems.extend(cpu.problems(cores))
            supported, why = cpu.supported()
            if not supported:
                result.warnings.append(f"{why}, so the server will use every core.")
        if self.start_guard:
            result.problems.extend(self.start_guard())
        if self.start_warnings:
            result.warnings.extend(self.start_warnings())
        content = self.config.server_type.content
        if content and not self.config.mods_dir.is_dir():
            result.warnings.append(f"The {content} folder is missing: {self.config.mods_dir}")
        if self.eula_not_accepted():
            result.problems.append(
                "Minecraft's rules (the EULA) haven't been accepted for this server yet, "
                "so it won't start. Accept them in Server settings."
            )
        try:
            free_gb = shutil.disk_usage(directory).free / 1024**3
            if free_gb < 2:
                result.problems.append(f"Only {free_gb:.1f} GB free on the server drive")
            elif free_gb < self.config.thresholds.disk_free_gb:
                result.warnings.append(f"Low disk space: {free_gb:.1f} GB free")
        except OSError as exc:  # pragma: no cover
            result.warnings.append(f"Could not read disk usage: {exc}")
        return result

    def status(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "name": self.config.server.name,
            "state": self.state.value,
            "state_verified": self.state is not ServerState.UNKNOWN,
            "state_verified_at": self.state_verified_at,
            "state_source": self._state_source(),
            "pid": self.pid,
            "uptime": self.uptime,
            "started_at": self.started_at,
            "online_at": self.online_at,
            "startup_seconds": self.startup_seconds,
            "last_exit_code": self.last_exit_code,
            "last_exit_reason": self.last_exit_reason.value if self.last_exit_reason else None,
            "server_type": self.config.server.type,
            "server_type_name": self.config.server_type.name,
            "server_type_detected": self.detected_type,
            "minecraft_version": self.mc_version,
            "minecraft_version_source": "server console" if self.mc_version else None,
            "pending_version": self.pending_version,
            "fabric_loader": self.loader_version,
            "fabric_loader_source": "server console" if self.loader_version else None,
            "loader_version": self.loader_version,
            "loader_name": self.loader_name or self.config.server_type.loader_name,
            "eula_required": self.eula_required or self.eula_not_accepted(),
            "java_version": self.java_version,
            "java": self.java_info.to_dict() if self.java_info else None,
            "java_compatibility": self.java_compatibility(),
            "port": self.detected_port or self.config.server.port,
            "directory": str(self.config.server_dir),
            "memory": " ".join(str(a) for a in self.config.server.jvm_args),
            "cpu_cores": cpu.status(
                self.pid if self.running else None, self.config.server.cpu_cores
            ),
            "max_players": self.config.server.max_players,
            "mod_count": self.mod_count,
            "tps": self.tps,
            "mspt": self.mspt,
            "tps_updated": self.tps_updated,
            "tps_source": self.tps_source,
            "tps_status": self.tps_status,
            "tps_unavailable_reason": self.tps_unavailable_reason(),
            "auto_restart": self.config.monitor.auto_restart,
            "auto_restart_blocked": self.auto_restart_blocked,
            "auto_restart_block_reason": self.auto_restart_block_reason,
            "restart_at": self.restart_at,
            "restart_delay": self.restart_delay,
            "restart_in": max(0.0, self.restart_at - time.time()) if self.restart_at else None,
            "auto_restart_cancelled": self.auto_restart_cancelled,
            "maintenance": self.maintenance,
            "stopped_for_sleep": self.stopped_for_sleep,
            "autosleep": self.config.server.autosleep,
            "autosleep_minutes": self.config.server.autosleep_minutes,
            "recent_crashes": self.recent_crash_count(),
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    async def _set_state(
        self, state: ServerState, message: str = "", level: str = "info", **data
    ) -> None:
        previous = self.state
        self.state = state
        self.last_state_change = time.time()
        self.state_verified_at = time.time()
        await self.bus.publish(
            Event(
                type="state",
                message=message or f"{previous.value} to {state.value}",
                level=level,
                data={"state": state.value, "previous": previous.value, **data},
            )
        )

    def _emit_console(self, raw: str, source: str = "agent") -> ConsoleLine:
        line = self.console.append(raw, source=source)
        self.bus.publish_soon(Event(type="console", message=raw, data=line.to_dict()))
        return line

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------
    async def start(self, actor: str = "system", _from_pending: bool = False) -> dict[str, Any]:
        async with self._lock:
            if self.state in (ServerState.STARTING, ServerState.ONLINE, ServerState.STOPPING):
                raise ServerError(
                    f"The server is already {self.state.value.lower()}; start ignored"
                )
            if self.state == ServerState.RESTART_PENDING and not _from_pending:
                # Enforced here, not only in the dashboard: a second start while
                # the countdown runs would race the automatic restart.
                raise ServerError(
                    "An automatic restart is already scheduled. "
                    "Use Restart Now to start immediately, or Cancel to stay stopped."
                )
            if not _from_pending and self._restart_task and not self._restart_task.done():
                self._restart_task.cancel()
            self.restart_at = None
            self.restart_delay = None
            self.auto_restart_cancelled = False
            pre = self.preflight()
            if not pre.ok:
                await self._set_state(
                    ServerState.OFFLINE,
                    "Start blocked by preflight checks",
                    level="error",
                    preflight=pre.to_dict(),
                )
                raise ServerError("; ".join(pre.problems))

            cmd = self.build_command()
            self._stop_requested = False
            self._stop_reason = ExitReason.UNKNOWN
            self._restart_after_stop = False
            self._online_event.clear()
            self._exited_event.clear()
            self.startup_seconds = None
            self.online_at = None
            self.startup_confirmed = False
            self.stopped_for_sleep = False
            self.started_at = time.time()
            await self._set_state(ServerState.STARTING, "Starting Minecraft", command=cmd)
            self._emit_console(f"[agent] launching: {' '.join(cmd)}")

            # NEW_PROCESS_GROUP keeps a Ctrl-C in the agent from reaching Minecraft.
            # NO_WINDOW stops Windows giving java.exe its own console window when
            # the agent runs without one (i.e. when started by Windows) - a window
            # that would kill the server if someone closed it.
            from ..winproc import NEW_PROCESS_GROUP, NO_WINDOW

            creationflags = NEW_PROCESS_GROUP | NO_WINDOW
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(self.config.server_dir),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except (OSError, ValueError) as exc:
                self.started_at = None
                self._exited_event.set()
                await self._set_state(
                    ServerState.OFFLINE, f"Could not launch Minecraft: {exc}", level="error"
                )
                raise ServerError(f"Could not launch Minecraft: {exc}") from exc

            self.pid = self.process.pid
            if self.config.server.cpu_cores:
                await self.apply_cpu_cores()
            self._reader_task = asyncio.create_task(self._pump_output(), name="mc-console")
            self._waiter_task = asyncio.create_task(self._wait_exit(), name="mc-wait")
            if self.db:
                self.db.add_event(
                    self.server_id, "server_start_requested", f"Start requested by {actor}"
                )
            return {"pid": self.pid, "command": cmd}

    async def apply_cpu_cores(self) -> dict[str, Any]:
        """Limit the running process to ``server.cpu_cores`` (every core when
        it is empty) and report what the operating system says it now uses."""
        if not self.running or not self.pid:
            return {"ok": False, "applied": None, "reason": "The server is not running"}
        cores = list(self.config.server.cpu_cores)
        result = cpu.apply(self.pid, cores)
        if result["ok"]:
            used = result["applied"]
            message = (
                f"Using cores {cpu.describe(used)} of {cpu.logical_cores()}"
                if cores
                else "Using every core"
            )
            await self.bus.publish(
                Event(type="cpu_cores", message=message, data={**result, "configured": cores})
            )
        else:
            await self.bus.publish(
                Event(
                    type="cpu_cores_failed",
                    level="warn",
                    message=f"The CPU core limit was not applied: {result['reason']}",
                    data={**result, "configured": cores},
                )
            )
        return result

    async def wait_online(self, timeout: float | None = None) -> bool:
        timeout = timeout or self.config.server.start_timeout
        try:
            await asyncio.wait_for(self._online_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def wait_exit(self, timeout: float = 60) -> bool:
        try:
            await asyncio.wait_for(self._exited_event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    # ------------------------------------------------------------------
    # console pump
    # ------------------------------------------------------------------
    async def _pump_output(self) -> None:
        assert self.process and self.process.stdout
        stream = self.process.stdout
        while True:
            try:
                chunk = await stream.readline()
            except (asyncio.LimitOverrunError, ValueError):
                continue  # absurdly long line: skip, do not die
            except Exception:  # pragma: no cover
                log.exception("console reader failed")
                break
            if not chunk:
                break
            raw = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
            if not raw:
                continue
            line = self.console.append(raw, source="stdout")
            await self.bus.publish(Event(type="console", message=raw, data=line.to_dict()))
            try:
                await self._handle_signals(line)
            except Exception:
                log.exception("signal handling failed")

    async def _handle_signals(self, line: ConsoleLine) -> None:
        sig = extract_signals(line, self.config.server_type.dialect)
        if sig.started and self.started_at:
            # Bedrock says "Server started." without a time; it is measured
            # from the launch.
            sig.done_seconds = round(time.time() - self.started_at, 1)
        if sig.mc_version:
            self.mc_version = sig.mc_version
        if sig.loader_version:
            self.loader_version = sig.loader_version
        if sig.loader_name:
            from .. import servertypes

            self.loader_name = sig.loader_name
            self.detected_type = servertypes.detected_type(sig.loader_name)
        if sig.eula_required:
            self.eula_required = True
        if sig.port:
            self.detected_port = sig.port
        if sig.mod_count is not None:
            self.mod_count = sig.mod_count
        if sig.tps is not None:
            self.tps, self.tps_updated = sig.tps, time.time()
            self.tps_source = self.config.monitor.tps_command
        if sig.target_tps is not None:
            self._target_tps = sig.target_tps
        if sig.mspt is not None:
            self.mspt, self.tps_updated = sig.mspt, time.time()
            if sig.tps is None and self._target_tps and sig.mspt > 0:
                # Derived from a measurement: a server that needs longer than
                # 1000/target ms per tick cannot reach its target rate.
                self.tps = round(min(self._target_tps, 1000.0 / sig.mspt), 2)
            self.tps_source = self.tps_source or str(self.config.monitor.tps_command)

        # A version change is only done once the console reports the new
        # version. Until then the dashboard shows it as pending.
        pending = self.pending_version
        if pending and self.mc_version and self.mc_version == pending.get("minecraft_version"):
            self.pending_version = None
            await self.bus.publish(
                Event(
                    type="version_confirmed",
                    level="success",
                    message=f"The server is now running Minecraft {self.mc_version}",
                    data={**pending, "confirmed_by": "server console"},
                )
            )

        if sig.done_seconds is not None and self.state == ServerState.STARTING:
            self.startup_seconds = sig.done_seconds
            self.online_at = time.time()
            self.startup_confirmed = True
            self._online_event.set()
            await self._set_state(
                ServerState.ONLINE,
                f"Online in {sig.done_seconds:.1f}s",
                level="success",
                startup_seconds=sig.done_seconds,
            )
            await self.bus.publish(
                Event(
                    type="server_started",
                    message="Server started successfully",
                    level="success",
                    data={"startup_seconds": sig.done_seconds},
                )
            )
        if sig.stopping and self.state == ServerState.ONLINE and not self._stop_requested:
            self._stop_reason = ExitReason.CLEAN_EXIT
            await self._set_state(ServerState.STOPPING, "Server is shutting down")

        if self.signal_hook:
            await self.signal_hook(sig, line)

    # ------------------------------------------------------------------
    # stop / restart
    # ------------------------------------------------------------------
    async def stop(
        self,
        actor: str = "system",
        reason: ExitReason = ExitReason.USER_STOP,
        timeout: float | None = None,
        restart: bool = False,
    ) -> dict[str, Any]:
        if not self.running:
            raise ServerError("The server isn't running.")
        timeout = timeout if timeout is not None else self.config.server.stop_timeout
        self._stop_requested = True
        self._stop_reason = reason
        self._restart_after_stop = restart
        await self._set_state(ServerState.STOPPING, f"Stop requested by {actor}")
        if self.db:
            self.db.add_event(self.server_id, "server_stop_requested", f"Stop requested by {actor}")

        sent = await self.send_command("stop", internal=True)
        forced = False
        assert self.process is not None  # self.running checked above
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except TimeoutError:
            forced = True
            self._emit_console(
                f"[agent] graceful stop timed out after {timeout:.0f}s, terminating process"
            )
            self._stop_reason = ExitReason.FORCE_KILLED
            await self._terminate()
        await self.wait_exit(timeout=30)
        return {"graceful": not forced, "command_sent": sent}

    async def _terminate(self) -> None:
        if not self.process:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=20)
        except TimeoutError:  # pragma: no cover
            with contextlib.suppress(ProcessLookupError, OSError):
                self.process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.process.wait(), timeout=10)

    async def kill(self, actor: str = "system") -> None:
        """Operator-requested force kill. Deliberately not a crash."""
        if not self.running:
            raise ServerError("The server isn't running.")
        self._stop_requested = True
        self._stop_reason = ExitReason.FORCE_KILLED
        self._emit_console(f"[agent] force kill requested by {actor}")
        await self._terminate()
        await self.wait_exit(timeout=30)

    async def restart(self, actor: str = "system", delay: float = 0.0) -> dict[str, Any]:
        if self.running:
            await self._set_state(ServerState.RESTARTING, f"Restart requested by {actor}")
            await self.stop(actor=actor, reason=ExitReason.USER_STOP, restart=True)
            deadline = time.time() + 120
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if self.state in (ServerState.STARTING, ServerState.ONLINE):
                    return {"restarted": True, "pid": self.pid}
            return {"restarted": False, "error": "Server did not come back up"}
        if delay:
            await asyncio.sleep(delay)
        result = await self.start(actor=actor)
        return {"restarted": True, **result}

    # ------------------------------------------------------------------
    # exit handling
    # ------------------------------------------------------------------
    async def _wait_exit(self) -> None:
        assert self.process
        code = await self.process.wait()
        if self._reader_task:
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(self._reader_task), timeout=10)
        await self._on_exit(code)

    def _saw_clean_shutdown(self) -> bool:
        markers = (
            "Stopping the server",
            "Stopping server",
            "Saving worlds",
            "Server closed",
            "Quit correctly",  # Bedrock
        )
        return any(any(mk in ln.raw for mk in markers) for ln in self.console.tail(60))

    def _classify_exit(self, code: int) -> ExitReason:
        if self._stop_requested:
            return (
                self._stop_reason
                if self._stop_reason != ExitReason.UNKNOWN
                else ExitReason.USER_STOP
            )
        if self._stop_reason == ExitReason.CLEAN_EXIT:
            return ExitReason.CLEAN_EXIT
        if self.state == ServerState.STARTING:
            return ExitReason.STARTUP_FAILURE
        if code == 0 and self._saw_clean_shutdown():
            return ExitReason.CLEAN_EXIT
        return ExitReason.CRASH

    async def _on_exit(self, code: int) -> None:
        self.last_exit_code = code
        reason = self._classify_exit(code)
        self.last_exit_reason = reason
        pid, self.pid = self.pid, None
        uptime = self.uptime
        restart_wanted = self._restart_after_stop
        self._restart_after_stop = False
        self.process = None
        self._online_event.clear()
        self.startup_confirmed = False
        self.tps = self.mspt = None
        self.tps_source = None
        self.tps_asked_at = None
        self._emit_console(f"[agent] process {pid} exited with code {code} ({reason.value})")

        if reason in NORMAL_REASONS or reason == ExitReason.FORCE_KILLED:
            self.started_at = None
            await self._set_state(
                ServerState.OFFLINE,
                "Server stopped" if reason != ExitReason.FORCE_KILLED else "Server force stopped",
                exit_code=code,
                reason=reason.value,
            )
            await self.bus.publish(
                Event(
                    type="server_stopped",
                    message="Server stopped",
                    data={"exit_code": code, "reason": reason.value, "uptime": uptime},
                )
            )
            self._exited_event.set()
            if restart_wanted:
                await asyncio.sleep(1.0)
                try:
                    await self.start(actor="restart")
                except ServerError as exc:
                    await self.bus.publish(
                        Event(
                            type="server_restart_failed",
                            message=f"Restart failed: {exc}",
                            level="error",
                        )
                    )
                else:
                    await self.bus.publish(
                        Event(type="server_restarted", message="Server restarted", level="success")
                    )
            return

        # ---------------- crash path ----------------
        self.started_at = None
        self._crash_times.append(time.time())
        await self._set_state(
            ServerState.CRASHED,
            "Server crashed" if reason == ExitReason.CRASH else "Server failed to start",
            level="error",
            exit_code=code,
            reason=reason.value,
        )
        context: dict[str, Any] = {"exit_code": code, "reason": reason.value, "uptime": uptime}
        if self.crash_hook:
            try:
                context = await self.crash_hook(code, reason) or context
            except Exception:
                log.exception("crash hook failed")
        await self.bus.publish(
            Event(type="server_crashed", message="Server crashed", level="error", data=context)
        )
        self._exited_event.set()
        self._restart_task = asyncio.create_task(self._maybe_auto_restart())

    def recent_crash_count(self) -> int:
        window = self.config.monitor.crash_window_minutes * 60
        cutoff = time.time() - window
        return len([t for t in self._crash_times if t >= cutoff])

    async def _maybe_auto_restart(self) -> None:
        if not self.config.monitor.auto_restart or self.auto_restart_blocked:
            return
        if self.maintenance and self.config.maintenance.block_auto_restart:
            await self.bus.publish(
                Event(
                    type="auto_restart_skipped",
                    message="Automatic restart skipped: maintenance mode is on",
                    level="warn",
                )
            )
            return
        max_crashes = self.config.monitor.max_crashes
        window_min = self.config.monitor.crash_window_minutes
        recent = self.recent_crash_count()
        if recent >= max_crashes:
            self.auto_restart_blocked = True
            self.auto_restart_block_reason = f"{recent} crashes within {window_min:.0f} minutes"
            await self.bus.publish(
                Event(
                    type="crash_loop",
                    message=f"Automatic restart disabled: {self.auto_restart_block_reason}",
                    level="error",
                    data={
                        "crashes": recent,
                        "window_minutes": window_min,
                        "max_crashes": max_crashes,
                    },
                )
            )
            return
        delay = self.config.monitor.restart_delay
        self.restart_delay = delay
        self.restart_at = time.time() + delay
        await self._set_state(
            ServerState.RESTART_PENDING,
            f"Restarting automatically in {delay:.0f}s",
            level="warn",
            restart_at=self.restart_at,
            delay=delay,
        )
        log.info("restart_scheduled delay=%.0fs crash=%d/%d", delay, recent, max_crashes)
        await self.bus.publish(
            Event(
                type="restart_scheduled",
                message=f"Restarting automatically in {delay:.0f}s (crash {recent} of {max_crashes})",
                level="warn",
                data={"delay": delay, "restart_at": self.restart_at, "crash_count": recent},
            )
        )
        self._restart_sleeping = True
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return  # cancelled, or "restart now" took over
        finally:
            self._restart_sleeping = False
        try:
            await self._run_pending_restart("auto-restart")
        except ServerError:
            pass  # already published as auto_restart_failed

    async def _run_pending_restart(self, actor: str, forced: bool = False) -> dict[str, Any]:
        """Leave RESTART_PENDING by starting the server. Only this method may
        start from that state, and the lock in start() makes it single-shot."""
        try:
            result = await self.start(actor=actor, _from_pending=True)
        except ServerError as exc:
            self.restart_at = None
            await self.bus.publish(
                Event(
                    type="auto_restart_failed",
                    level="error",
                    message=f"The automatic restart could not start the server: {exc}",
                )
            )
            if self.state == ServerState.RESTART_PENDING:
                await self._set_state(
                    ServerState.CRASHED, "Automatic restart failed", level="error"
                )
            raise
        log.info("restart_started actor=%s forced=%s", actor, forced)
        await self.bus.publish(
            Event(
                type="restart_started",
                level="info",
                message="Starting the server after the crash",
                data={"actor": actor, "forced": forced},
            )
        )
        self._recovery_task = asyncio.create_task(self._announce_recovery(), name="mc-recovery")
        return result

    async def _announce_recovery(self) -> None:
        # "Recovered" only once startup has actually completed.
        if await self.wait_online():
            await self.bus.publish(
                Event(
                    type="server_recovered",
                    message="Server recovered after a crash",
                    level="success",
                    data={"startup_seconds": self.startup_seconds},
                )
            )

    def _pending_or_raise(self) -> None:
        if self.state != ServerState.RESTART_PENDING:
            raise ServerError(
                f"No automatic restart is pending (the server is {self.state.value.lower()})."
            )
        task = self._restart_task
        if task and not task.done() and not self._restart_sleeping:
            # The countdown already reached zero and the start is under way.
            # Interrupting it now could leave a half-launched process.
            raise ServerError("The automatic restart is already starting the server.")

    async def restart_now(self, actor: str = "system") -> dict[str, Any]:
        """Skip the rest of the countdown and start immediately."""
        self._pending_or_raise()
        task = self._restart_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        log.info("restart_forced actor=%s", actor)
        await self.bus.publish(
            Event(type="restart_forced", level="info", message=f"Restart now requested by {actor}")
        )
        return await self._run_pending_restart(actor, forced=True)

    async def cancel_pending_restart(self, actor: str = "system") -> dict[str, Any]:
        """Stop the countdown. The server stays stopped."""
        self._pending_or_raise()
        task = self._restart_task
        if task and not task.done():
            task.cancel()
        self.restart_at = None
        self.restart_delay = None
        self.auto_restart_cancelled = True
        await self._set_state(ServerState.CRASHED, f"Automatic restart cancelled by {actor}")
        log.info("restart_cancelled actor=%s", actor)
        await self.bus.publish(
            Event(
                type="restart_cancelled",
                level="info",
                message="Automatic restart cancelled. The server will stay stopped.",
            )
        )
        return {"cancelled": True}

    def clear_crash_block(self) -> None:
        self._crash_times.clear()
        self.auto_restart_blocked = False
        self.auto_restart_block_reason = None

    # ------------------------------------------------------------------
    # console commands
    # ------------------------------------------------------------------
    async def send_command(self, command: str, internal: bool = False) -> bool:
        """Write one Minecraft console command to the server's stdin.

        Commands are validated in agent.minecraft.commands before they reach
        this method; here we additionally refuse embedded newlines so one call
        can never become two commands.
        """
        if not self.running or not self.process or not self.process.stdin:
            raise ServerError("The server isn't running.")
        if "\n" in command or "\r" in command:
            raise ServerError("A command has to be one line.")
        try:
            self.process.stdin.write((command.strip() + "\n").encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, RuntimeError, OSError) as exc:
            raise ServerError(f"Could not write to the server console: {exc}") from exc
        if not internal:
            self._emit_console(f"> {command.strip()}", source="command")
        return True

    async def shutdown(self) -> None:
        """Called when the agent itself stops. Minecraft is left running."""
        for task in (self._reader_task, self._waiter_task, self._restart_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
