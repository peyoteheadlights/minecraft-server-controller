"""Pictures of every setup screen, in light and dark, to check the design.

    python scripts/installer_shots.py            (writes ui-shots/installer/*.png)

It drives the real setup window with a pretend wizard
(installer/app/demo.py), so nothing on this PC is changed. On a machine
with no screen it draws off-screen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "ui-shots" / "installer"


def main() -> int:
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from installer.app.demo import DemoWizard
    from installer.app.window import SetupWindow

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    OUT.mkdir(parents=True, exist_ok=True)

    def snap(window: SetupWindow, name: str) -> None:
        app.processEvents()
        path = OUT / f"{name}-{'dark' if window.dark else 'light'}.png"
        window.grab().save(str(path))
        print(f"wrote {path.relative_to(ROOT)}")

    for dark in (False, True):
        w = SetupWindow(DemoWizard(java=False), dark=dark)
        w.show()
        snap(w, "01-welcome")
        w.servers_screen()
        server = w.answers["servers"][0]
        server.update(
            folder="C:\\Minecraft\\Survival", name="Survival", ok=True, type_name="Fabric"
        )
        w.answers["servers"].append(
            {
                "folder": "C:\\Minecraft\\missing",
                "name": "",
                "color": "teal",
                "type": "",
                "ok": False,
                "problem": "That folder isn't there. Pick the folder your server is in.",
            }
        )
        w.servers_screen()
        snap(w, "02-servers")
        w.answers["servers"].pop()
        w.password_screen()
        snap(w, "03-password")
        w.java_screen()
        snap(w, "04-java")
        w.answers["advanced_open"] = True
        w.options_screen()
        snap(w, "05-options")
        w.phone_screen()
        snap(w, "06-phone")
        w.run()
        w.wizard.advance(3)
        w.poll()
        snap(w, "07-progress")
        w.wizard.advance(10)
        w.poll()
        snap(w, "08-done")
        w.close()

        failing = SetupWindow(
            DemoWizard(
                found=[
                    {
                        "describe": "We found Minecraft Server Controller 1.1.0 with 2 servers.",
                        "program_dir": "C:\\Users\\Mark\\minecraft-server-controller",
                        "action": "migrate",
                        "refused": None,
                        "servers": [
                            {"id": "survival", "name": "Survival", "java": "java", "major": 17},
                            {"id": "creative", "name": "Creative", "java": "java", "major": None},
                        ],
                    }
                ],
                java=False,
                fail_at=5,
            ),
            dark=dark,
        )
        failing.show()
        snap(failing, "09-found")
        failing.update_found(0)
        failing.wizard.advance(5)
        failing.poll()
        snap(failing, "10-failed")
        failing.close()

        remove = SetupWindow(DemoWizard(uninstall=True), dark=dark)
        remove.show()
        snap(remove, "11-remove")
        remove.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
