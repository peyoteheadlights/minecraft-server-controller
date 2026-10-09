"""MinecraftServerController.exe: starts the agent, or opens the dashboard."""

import sys

from installer.cli import agent_entry

sys.exit(agent_entry())
