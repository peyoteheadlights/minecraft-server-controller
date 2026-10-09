"""setup.exe: the one file people download.

It carries the whole app (``payload.zip``: the built program folder) and
does three small things, using only the standard library:

1. unpack the program into a fresh temporary folder, checking every file
   against the SHA-256 list built with it (``payload.json``);
2. run that new copy's ``mcsc.exe setup`` with the same arguments, which
   shows the installer's screens (or, with ``--quiet``, none);
3. clean up the temporary folder and return its exit code.

Run from inside the installed program folder (Start menu → setup, or
"Installed apps" → Uninstall), it first copies itself to a temporary folder
and runs from there, so the program folder can be replaced or removed.
Windows asks for Administrator rights once, up front (the file is built with
a manifest that requires them).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
RELAUNCHED = "--relaunched-from-temp"
# installer/apply_update.py's staging folder: "<program folder>.update".
UPDATE_FOLDER_SUFFIX = ".update"


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def unpack(payload: Path, manifest: dict, target: Path) -> Path:
    """Unpack and check every file. Raises on any mismatch."""
    with zipfile.ZipFile(payload) as archive:
        for member in archive.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError(f"unsafe path in the setup file: {name}")
        archive.extractall(target)
    for relative, expected in manifest["files"].items():
        digest = hashlib.sha256((target / relative).read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError(f"{relative} is damaged. Download the setup file again.")
    return target / "program"


def unpack_parent(me: Path) -> Path | None:
    """Where to unpack the program. An update the dashboard asked for runs
    from the folder next to the program folder that only Administrators can
    change (installer/apply_update.py), so it unpacks there too: the
    person's temporary folder can be changed by the app's own account,
    which must never be able to swap what this elevated setup runs. Any
    other run uses the usual temporary folder (None)."""
    return me.parent if me.parent.name.endswith(UPDATE_FOLDER_SUFFIX) else None


def message(text: str) -> None:
    """A plain Windows message box (setup.exe has no console)."""
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Minecraft Server Controller setup", 0x10)
    else:
        print(text, file=sys.stderr)


def main() -> int:
    args = sys.argv[1:]
    me = Path(sys.executable)
    if RELAUNCHED in args:
        args.remove(RELAUNCHED)
    elif (me.parent / "install.json").is_file():
        # Running from the installed folder: run a copy from elsewhere so the
        # folder can be replaced or removed.
        copy_dir = Path(tempfile.mkdtemp(prefix="mcsc-setup-"))
        copy = copy_dir / me.name
        shutil.copy2(me, copy)
        return subprocess.call([str(copy), RELAUNCHED, "--program-dir", str(me.parent), *args])

    folder = bundle_dir()
    try:
        manifest = json.loads((folder / "payload.json").read_text(encoding="utf-8"))
        staging = Path(tempfile.mkdtemp(prefix="mcsc-setup-files-", dir=unpack_parent(me)))
        program = unpack(folder / "payload.zip", manifest, staging)
    except Exception as exc:
        message(f"The setup file couldn't be opened: {exc}")
        return 3
    try:
        return subprocess.call(
            [str(program / "mcsc.exe"), "setup", "--setup-exe", str(me), *args],
            creationflags=NO_WINDOW,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
