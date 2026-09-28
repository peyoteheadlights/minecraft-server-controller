"""Run the agent as a Windows Service  (ALTERNATIVE - not the recommended method).

The recommended way to start the agent with Windows is the scheduled task:

    python -m installer.autostart enable

It runs the exact command that works manually. Use this service only if you
specifically need a Windows Service. The two must not both be installed.

History: this file originally registered the service class as
"__main__.MinecraftControlService", because `python -m installer.service`
runs this module as __main__. pythonservice.exe starts in a fresh interpreter
whose __main__ is empty, so the class was never found and the service could
not start - at boot or manually. It now registers the full file path, which is
what pywin32's own helper does.

Usage (open PowerShell as Administrator, in the project folder):

    python -m installer.service install
    python -m installer.service start
    python -m installer.service status
    python -m installer.service stop
    python -m installer.service uninstall

'install' registers the service with Windows so it starts at boot and
restarts itself if it ever exits unexpectedly. Uninstalling removes the
service and nothing else: your Minecraft folder, worlds, mods, backups and
the agent's database are left exactly where they are.

Requires pywin32:  pip install pywin32
If pywin32 is not available this module prints an equivalent NSSM recipe
instead of failing silently.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "MinecraftServerControl"
DISPLAY_NAME = "Minecraft Server Control agent"
DESCRIPTION = (
    "Starts, monitors and backs up the Fabric Minecraft server, and serves the "
    "control dashboard on the private Tailscale address."
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    import servicemanager  # type: ignore
    import win32event  # type: ignore
    import win32service  # type: ignore
    import win32serviceutil  # type: ignore

    HAVE_PYWIN32 = True
except ImportError:  # not on Windows, or pywin32 is missing
    HAVE_PYWIN32 = False


if HAVE_PYWIN32:

    class MinecraftControlService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.server = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self.server:
                self.server.should_exit = True
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.run_agent()

        def run_agent(self):
            # A Windows Service starts in C:\Windows\system32, not in the
            # project folder. Every path below is absolute and derived from
            # this file's location, and the working directory is set explicitly
            # so nothing relative can resolve into system32.
            os.chdir(str(PROJECT_ROOT))
            sys.path.insert(0, str(PROJECT_ROOT))
            import uvicorn

            from agent.config import Config
            from agent.logging_setup import setup_logging
            from agent.main import create_app, resolve_tls, TLSConfigError

            config = Config.load(PROJECT_ROOT / "config" / "config.yaml",
                                 PROJECT_ROOT / ".env")
            config.ensure_dirs()
            setup_logging(config.log_dir, level=str(config.get("logging.level", "INFO")),
                          console=False)
            logger = logging.getLogger("msc.service")
            logger.info("service starting from %s (cwd now %s)", PROJECT_ROOT, os.getcwd())

            ssl_files = None
            try:
                ssl_files = resolve_tls(config)
            except TLSConfigError as exc:
                # Do not silently fall back to plain HTTP: that would put
                # credentials on the wire. Fail loudly in the event log.
                logger.error("HTTPS could not start: %s", exc)
                servicemanager.LogErrorMsg(f"Minecraft Server Control: HTTPS could not start: {exc}")
                raise

            app = create_app(config)
            uvicorn_config = uvicorn.Config(
                app,
                host=str(config.get("network.host", "127.0.0.1")),
                port=int(config.get("network.port", 8765)),
                log_level="info",
                access_log=False,
                ssl_certfile=ssl_files[0] if ssl_files else None,
                ssl_keyfile=ssl_files[1] if ssl_files else None,
            )
            logger.info("serving on %s", config.base_url)
            self.server = uvicorn.Server(uvicorn_config)
            self.server.run()


def _query_task() -> tuple[int, str, str]:
    try:
        proc = subprocess.run(["schtasks.exe", "/Query", "/TN", "Minecraft Server Control"],
                              capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError):
        return 1, "", ""


def _sc(*args: str) -> int:
    """Call Windows' own sc.exe for the settings pywin32 does not expose."""
    return subprocess.call(["sc.exe", *args])


def service_class_string() -> str:
    """The value pythonservice.exe reads to find the service class.

    It must be "<full path to this file without .py>.<ClassName>".
    pythonservice.exe adds that directory to sys.path and imports the module
    by file name in a fresh interpreter. Using __name__ here was the original
    bug: under `python -m` it is "__main__", which the fresh interpreter cannot
    resolve.
    """
    return os.path.splitext(str(Path(__file__).resolve()))[0] + ".MinecraftControlService"


def install() -> int:
    if not HAVE_PYWIN32:
        print_nssm_instructions()
        return 1
    code, _, _ = _query_task()
    if code == 0:
        print("The scheduled task 'Minecraft Server Control' is already registered.")
        print("Installing the service as well would start two agents fighting over one port.")
        print("Remove the task first:  python -m installer.autostart disable")
        return 1
    win32serviceutil.InstallService(
        pythonClassString=service_class_string(),
        serviceName=SERVICE_NAME,
        displayName=DISPLAY_NAME,
        description=DESCRIPTION,
        startType=win32service.SERVICE_AUTO_START,
    )
    # Restart the service if it exits unexpectedly: after 30s, then 60s, then
    # every 120s. The reset window is one day.
    _sc("failure", SERVICE_NAME, "reset=", "86400",
        "actions=", "restart/30000/restart/60000/restart/120000")
    print(f"Installed '{SERVICE_NAME}'. It will start automatically at boot.")
    print("Start it now with: python -m installer.service start")
    return 0


def uninstall() -> int:
    if not HAVE_PYWIN32:
        print(f"Without pywin32, remove it with:  nssm remove {SERVICE_NAME} confirm")
        return 1
    try:
        win32serviceutil.StopService(SERVICE_NAME)
    except Exception:
        pass
    win32serviceutil.RemoveService(SERVICE_NAME)
    print(f"Removed the '{SERVICE_NAME}' service.")
    print("Nothing else was deleted: your Minecraft folder, worlds, mods, backups")
    print("and the agent's data folder are untouched.")
    return 0


def start() -> int:
    """Start the service and report what actually happened.

    The original version printed "Service starting." and returned, which hid
    the fact that the service died immediately.
    """
    import time
    win32serviceutil.StartService(SERVICE_NAME)
    state = None
    for _ in range(30):
        time.sleep(1)
        state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        if state in (win32service.SERVICE_RUNNING, win32service.SERVICE_STOPPED):
            break
    if state == win32service.SERVICE_RUNNING:
        print("Service is RUNNING (verified).")
        return 0
    print("Service did NOT reach the running state. Check the Windows Application event log")
    print("for 'Python Service' errors, and logs/startup.log in the project folder.")
    return 1


def stop() -> int:
    win32serviceutil.StopService(SERVICE_NAME)
    print("Service stopping. Minecraft itself is not stopped by this;")
    print("stop the Minecraft server from the dashboard first if you want it down.")
    return 0


def status() -> int:
    if not HAVE_PYWIN32:
        return _sc("query", SERVICE_NAME)
    states = {
        win32service.SERVICE_STOPPED: "stopped",
        win32service.SERVICE_START_PENDING: "starting",
        win32service.SERVICE_STOP_PENDING: "stopping",
        win32service.SERVICE_RUNNING: "running",
    }
    try:
        code = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        print(f"{SERVICE_NAME}: {states.get(code, code)}")
        return 0
    except Exception as exc:
        print(f"{SERVICE_NAME} is not installed ({exc})")
        return 1


def print_nssm_instructions() -> None:
    python = sys.executable
    print("pywin32 is not installed, so the built-in service wrapper cannot be used.")
    print("Either install it:")
    print("    pip install pywin32")
    print()
    print("or use NSSM (https://nssm.cc), which works just as well:")
    print(f'    nssm install {SERVICE_NAME} "{python}" "-m" "agent.main"')
    print(f'    nssm set {SERVICE_NAME} AppDirectory "{PROJECT_ROOT}"')
    print(f'    nssm set {SERVICE_NAME} Start SERVICE_AUTO_START')
    print(f'    nssm set {SERVICE_NAME} AppStdout "{PROJECT_ROOT}\\logs\\service-out.log"')
    print(f'    nssm set {SERVICE_NAME} AppStderr "{PROJECT_ROOT}\\logs\\service-err.log"')
    print(f"    nssm start {SERVICE_NAME}")


COMMANDS = {"install": install, "uninstall": uninstall, "start": start,
            "stop": stop, "status": status}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] in COMMANDS:
        return COMMANDS[argv[1]]()
    if HAVE_PYWIN32 and len(argv) == 1:
        # Windows starts the service by launching this file with no arguments.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MinecraftControlService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    print(__doc__)
    print(f"Commands: {', '.join(COMMANDS)}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
