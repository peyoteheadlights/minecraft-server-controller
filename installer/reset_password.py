"""Forgot the dashboard password? Set a new one, on the PC itself.

    python -m installer.reset_password

There is no way to do this from the dashboard or over the network: whoever
can run this can already sign in to the PC. It asks for the new password
twice (nothing shows while typing), stores only its hash in .env, and signs
every session out, the owner's and helpers', so a phone left signed in
somewhere needs the new password too. The password itself is never shown,
logged or saved.

A running agent picks the new password up by itself (it notices .env
changed); there is no need to restart it.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import appinfo
from installer.setup_tool import write_env_value

MIN_LENGTH = 10


def ask_new_password(ask: Callable[[str], str], say: Callable[[str], None]) -> str | None:
    for _ in range(3):
        first = ask("New password (10+ characters): ")
        if len(first) < MIN_LENGTH:
            say("  Too short: use at least 10 characters.")
            continue
        if ask("Type it again: ") != first:
            say("  The two didn't match.")
            continue
        return first
    return None


def reset(
    config_path: Path,
    env_path: Path,
    ask: Callable[[str], str] = getpass.getpass,
    say: Callable[[str], None] = print,
) -> int:
    from agent.config import Config
    from agent.database.db import Database
    from agent.datafolder import use_data_in_use
    from agent.security.auth import hash_password

    say("Minecraft Server Control - reset the dashboard password")
    say("Nothing appears while you type. That is normal.")
    password = ask_new_password(ask, say)
    if password is None:
        say("Nothing was changed.")
        return 1
    hashed = hash_password(password)
    del password
    config = Config.load(config_path, env_path)
    use_data_in_use(config)
    write_env_value(env_path, "MCSC_ADMIN_PASSWORD_HASH", hashed)
    db = Database(config.database_path)
    signed_out = db.execute("DELETE FROM sessions").rowcount
    owner = config.admin_username
    # A lockout from the forgotten password's attempts would otherwise keep
    # the owner out with the new one.
    db.execute("DELETE FROM login_attempts WHERE success = 0 AND user = ?", (owner,))
    db.audit("password_reset", user=owner, target=owner, detail="reset on the PC")
    db.close()
    say(f"Done. The password for '{owner}' is changed.")
    say(f"Signed out {signed_out} session(s). Sign in again with the new password.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, default=appinfo.default_config_path())
    parser.add_argument("--env", type=Path, default=appinfo.default_env_path())
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Run this in a PowerShell window on the PC, so the password can be typed.")
        return 2
    return reset(args.config, args.env)


if __name__ == "__main__":
    raise SystemExit(main())
