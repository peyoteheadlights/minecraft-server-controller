"""mcsc.exe: the same program, for typed commands (mcsc check, mcsc version...)."""

import sys

from installer.cli import cli_entry

sys.exit(cli_entry())
