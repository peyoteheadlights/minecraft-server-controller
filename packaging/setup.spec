# PyInstaller recipe for the one-file installer:
#   MinecraftServerController-Setup-<version>.exe
# It holds build/payload/payload.zip (the program folder) and its checksum
# list, and asks Windows for Administrator rights once, up front.
# Built by scripts/build_installer.py on Windows; see docs/developers.md.
# -*- mode: python -*-
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (PyInstaller defines SPECPATH)
PAYLOAD = ROOT / "build" / "payload"
NAME = os.environ["MCSC_SETUP_NAME"]

a = Analysis(  # noqa: F821
    [str(ROOT / "installer" / "bootstrap.py")],
    pathex=[],
    datas=[(str(PAYLOAD / "payload.zip"), "."), (str(PAYLOAD / "payload.json"), ".")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)  # noqa: F821
EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    icon=str(ROOT / "agent" / "web" / "icons" / "app.ico"),
    console=False,
    uac_admin=True,
    version=str(ROOT / "build" / "version-info.txt"),
)
