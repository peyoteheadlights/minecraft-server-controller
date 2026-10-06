"""Make the keys phone alerts need, on their own.

    python -m installer.make_push_keys

Setup (setup.ps1) already does this, so this is only for running the one
step by itself. It is the same step: keys that are already there and work
are kept, because replacing them signs every phone out.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from installer.setup_tool import Context, step_push_keys


def main() -> int:
    ctx = Context(mode="setup")
    step = step_push_keys(ctx)
    print(step.line())
    if step.status != "OK":
        return 1
    print("Restart the agent, then turn on Phone alerts in App settings and press")
    print("'Turn on for this phone' on each phone you want alerts on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
