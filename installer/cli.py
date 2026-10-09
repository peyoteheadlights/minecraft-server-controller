"""The two programs in an installed copy.

``MinecraftServerController.exe`` runs with no window. The startup task
runs it (``--launched-by task``) to start the agent, and the Start Menu
shortcut runs it with ``--open`` to open the dashboard (starting the agent
through its task first if it isn't running).

``mcsc.exe`` is the same program for typed commands:

    mcsc check                 read-only health check (same as setup.ps1 --check)
    mcsc check --deep          ...also tries a real secure connection
    mcsc reset-password        choose a new owner password (signs everyone out)
    mcsc import FILE --to DIR  import an "Export everything" file
    mcsc autostart status      the Windows startup task (also: test, run)
    mcsc setup ...             the installer's screens (setup.exe runs this)
    mcsc apply-update          run by the update task only (see docs/security.md)
    mcsc version
"""

from __future__ import annotations

import sys
import time


def open_dashboard() -> int:
    """Open the dashboard in the default browser, starting the agent first
    (as this person, through its task) if it isn't answering."""
    import os

    from agent.config import Config

    from . import autostart
    from .system import System

    config = Config.load()
    system = System()
    if not system.agent_answers(config.network.port, config.tls_enabled):
        autostart.run_tool(["schtasks.exe", "/Run", "/TN", autostart.TASK_NAME])
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if system.agent_answers(config.network.port, config.tls_enabled):
                break
            time.sleep(1)
    if hasattr(os, "startfile"):
        os.startfile(config.base_url + "/")
    return 0


def agent_entry(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--open"]:
        return open_dashboard()
    from agent.main import main

    return main(args)


def cli_entry(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command, rest = (args[0], args[1:]) if args else ("help", [])
    if command == "check":
        from agent.main import main

        return main(["--check", *rest])
    if command == "reset-password":
        from . import reset_password

        return reset_password.main(rest)
    if command == "import":
        from . import import_from_pc

        return import_from_pc.main(rest)
    if command == "autostart":
        from . import autostart

        return autostart.main(rest)
    if command == "setup":
        from . import wizard

        return wizard.main(rest)
    if command == "apply-update":
        from . import apply_update

        return apply_update.main(rest)
    if command == "open":
        return open_dashboard()
    if command == "version":
        from agent import API_VERSION, __version__

        print(f"Minecraft Server Controller {__version__} (API {API_VERSION})")
        return 0
    print(__doc__)
    return 0 if command in ("help", "--help", "-h") else 2
