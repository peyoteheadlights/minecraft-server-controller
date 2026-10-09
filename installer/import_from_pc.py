"""Import from another PC: put an "Export everything" file in place here.

    python -m installer.import_from_pc "D:\\minecraft-server-control-export.zip" --to "C:\\Minecraft Servers"

Run it on the new PC after setup.ps1 has installed the app, and before the
agent's first start (stop the agent first if it is already running). Each
server's folder goes inside the --to folder under its old folder name; a
folder that already has files in it is refused rather than written over.
config.yaml is pointed at the new folders (the old one is kept as
config.yaml.before-import-<time>), and schedules, players seen, mod sources
and backups go into this PC's database.

If the file was exported with passwords and keys, the passphrase is asked
for (nothing shows while typing) and .env gets them; otherwise run
setup.ps1 afterwards to choose a dashboard password, and add helpers again.
Either way, run setup.ps1 afterwards: the HTTPS certificate and the start
with Windows task belong to each PC and are made fresh.

This is a program run on the PC; nothing in the dashboard can start it.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import appinfo
from installer.setup_tool import write_env_value


def main(argv: list[str] | None = None, ask=getpass.getpass, say=print) -> int:
    from agent.transfer import TransferError, import_all, plan_import, read_manifest

    parser = argparse.ArgumentParser(description="Import from another PC.")
    parser.add_argument("export_file", type=Path)
    parser.add_argument("--to", type=Path, required=True, help="the folder to put the servers in")
    parser.add_argument("--config", type=Path, default=appinfo.default_config_path())
    parser.add_argument("--env", type=Path, default=appinfo.default_env_path())
    parser.add_argument("--yes", action="store_true", help="don't ask before starting")
    args = parser.parse_args(argv)

    try:
        manifest = read_manifest(args.export_file)
        if not args.to.is_absolute():
            raise TransferError("Give the whole path for --to, for example C:\\Minecraft Servers")
        places = plan_import(manifest, args.to)
    except (TransferError, OSError) as exc:
        say(f"Can't import: {exc}")
        return 1
    includes = manifest.get("includes", {})
    say("This file holds:")
    for place in places:
        say(f"  {place['name']}: {place['from']}  ->  {place['to']}")
    say(f"  worlds: {'yes' if includes.get('worlds') else 'no'}")
    say(f"  backups: {'yes' if includes.get('backups') else 'no'}")
    say(
        f"  passwords and keys: {'yes, locked with a passphrase' if includes.get('secrets') else 'no'}"
    )
    if not args.yes and input("Import it? [y/N] ").strip().lower() not in ("y", "yes"):
        say("Nothing was changed.")
        return 1
    passphrase = None
    if includes.get("secrets"):
        passphrase = ask("Passphrase the file was saved with (Enter to skip passwords): ") or None
    try:
        result = import_all(
            args.export_file,
            args.to,
            args.config,
            args.env,
            passphrase=passphrase,
            write_env=write_env_value,
        )
    except (TransferError, OSError) as exc:
        say(f"The import stopped: {exc}")
        return 1
    say(
        f"Done: {len(result['servers'])} server(s), {result['files']} files, "
        f"{result['backups']} backup(s), {result['helpers']} helper(s)."
    )
    if not result["secrets"]:
        say("Passwords and keys weren't imported. Run setup.ps1 to choose a dashboard password.")
    say("Now run setup.ps1, which makes this PC's certificate and start with Windows task.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
