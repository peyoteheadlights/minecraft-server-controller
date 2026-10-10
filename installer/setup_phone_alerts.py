"""Put the Firebase key on this PC, so the phone app gets lock-screen alerts.

    python -m installer.setup_phone_alerts C:\\path\\to\\downloaded-key.json
    python -m installer.setup_phone_alerts --remove

The key comes from your own Firebase project (mobile/README.md says how to
make one). It is checked, then copied into the data folder, into a folder
only this account and administrators can read. It never goes into the
repository or .env. Run it again with a new file to replace the key.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config
from agent.datafolder import use_data_in_use
from agent.notifications import fcm
from agent.security.certs import secure_directory


def install_key(config, source: Path) -> Path:
    """Check ``source`` and copy it into place. Raises fcm.FcmError."""
    account = fcm.load_service_account(source)
    target = fcm.key_path(config)
    secure_directory(target.parent)
    temporary = target.with_suffix(".part")
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, target)
    print(f"Firebase project: {account.project_id}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up lock-screen alerts for the phone app")
    parser.add_argument("key", nargs="?", help="The Firebase service account key (.json)")
    parser.add_argument("--remove", action="store_true", help="Remove the key from this PC")
    parser.add_argument("--config", help="Path to config.yaml")
    args = parser.parse_args(argv)
    config = Config.load(args.config)
    use_data_in_use(config)
    if args.remove:
        target = fcm.key_path(config)
        if target.exists():
            target.unlink()
            print("Removed. Phones no longer get lock-screen alerts from this PC.")
        else:
            print("There was no key on this PC.")
        return 0
    if not args.key:
        parser.error("give the downloaded key file, or --remove")
    try:
        target = install_key(config, Path(args.key))
    except fcm.FcmError as exc:
        print(f"Not set up: {exc}")
        return 1
    print(f"Saved to {target}")
    print("You can delete the downloaded copy now. Restart the agent, then turn on")
    print("lock-screen alerts in the phone app's Settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
