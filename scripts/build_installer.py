"""Build the Windows installer: dist/MinecraftServerController-Setup-<version>.exe

    python scripts/build_installer.py            (on Windows, with requirements-build.lock)

It runs in three steps, all inside build/ and dist/ (both git-ignored):

1. PyInstaller turns packaging/app.spec into the program folder
   dist/MinecraftServerController/ (MinecraftServerController.exe, mcsc.exe
   and everything they need, so the PC needs no Python).
2. That folder is zipped into build/payload/payload.zip, with
   build/payload/payload.json listing every file's SHA-256. The installer
   checks each file against this list as it unpacks.
3. PyInstaller turns packaging/setup.spec into the one-file installer that
   carries the zip, then the script writes the installer's own SHA-256 next
   to it (<name>.exe.sha256). The release workflow uploads both, and the
   in-app updater refuses an installer whose checksum doesn't match.

The version comes from agent/__init__.py and nowhere else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
PAYLOAD = BUILD / "payload"
PROGRAM = DIST / "MinecraftServerController"


def version() -> str:
    text = (ROOT / "agent" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("agent/__init__.py has no __version__")
    return match.group(1)


def setup_name(ver: str) -> str:
    return f"MinecraftServerController-Setup-{ver}"


def version_info(ver: str) -> str:
    """The Windows "Details" tab of each .exe (PyInstaller's format)."""
    parts = [int(p) for p in re.findall(r"\d+", ver)[:3]] + [0, 0, 0, 0]
    numbers = tuple(parts[:4])
    fields = {
        "CompanyName": "peyoteheadlights",
        "FileDescription": "Minecraft Server Controller",
        "FileVersion": ver,
        "InternalName": "MinecraftServerController",
        "LegalCopyright": "MIT License",
        "OriginalFilename": "MinecraftServerController.exe",
        "ProductName": "Minecraft Server Controller",
        "ProductVersion": ver,
    }
    strings = ",\n".join(f"          StringStruct({k!r}, {v!r})" for k, v in fields.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
{strings}
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def make_payload(program: Path, out: Path) -> tuple[Path, Path]:
    """Zip the program folder as program/... and list each file's SHA-256."""
    out.mkdir(parents=True, exist_ok=True)
    archive = out / "payload.zip"
    manifest = out / "payload.json"
    files: dict[str, str] = {}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(p for p in program.rglob("*") if p.is_file()):
            name = "program/" + path.relative_to(program).as_posix()
            zf.write(path, name)
            files[name] = sha256(path)
    manifest.write_text(
        json.dumps({"version": version(), "files": files}, indent=1) + "\n", encoding="utf-8"
    )
    return archive, manifest


def pyinstaller(spec: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "pyinstaller"),
            str(spec),
        ],
        cwd=ROOT,
        check=True,
        env={**os.environ, **(env or {})},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--payload-only",
        action="store_true",
        help="only zip an already built dist/MinecraftServerController",
    )
    args = parser.parse_args(argv)
    if sys.platform != "win32" and not args.payload_only:
        print("The installer is built on Windows (the GitHub workflow uses windows-latest).")
        return 2
    ver = version()
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version-info.txt").write_text(version_info(ver), encoding="utf-8")
    if not (ROOT / "agent" / "web" / "icons" / "app.ico").is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icons.py")], check=True)
    if not args.payload_only:
        shutil.rmtree(PROGRAM, ignore_errors=True)
        pyinstaller(ROOT / "packaging" / "app.spec")
    archive, _ = make_payload(PROGRAM, PAYLOAD)
    print(f"payload: {archive} ({archive.stat().st_size // 1024} KB)")
    if args.payload_only:
        return 0
    name = setup_name(ver)
    pyinstaller(ROOT / "packaging" / "setup.spec", {"MCSC_SETUP_NAME": name})
    setup = DIST / f"{name}.exe"
    checksum = DIST / f"{name}.exe.sha256"
    checksum.write_text(f"{sha256(setup)}  {setup.name}\n", encoding="utf-8")
    print(f"installer: {setup} ({setup.stat().st_size // (1024 * 1024)} MB)")
    print(f"checksum:  {checksum.read_text(encoding='utf-8').strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
