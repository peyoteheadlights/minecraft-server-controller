"""Windows process-creation flags.

When the agent runs without a console - which is how Windows startup runs it
- every console program it launches (java.exe, tailscale.exe, icacls.exe,
schtasks.exe) would otherwise be given a brand-new console window. For
Minecraft that is dangerous: closing that stray window kills the server.

CREATE_NO_WINDOW stops that. Output is still captured through pipes, and
input (the Minecraft `stop` command) still goes through stdin.
"""

from __future__ import annotations

import os
import subprocess

NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
NEW_PROCESS_GROUP: int = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
)
