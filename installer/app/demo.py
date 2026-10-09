"""A pretend ``Wizard`` that changes nothing, for the window's tests and
screenshots (``python scripts/installer_shots.py``). It answers like the
real one, with made-up but plausible folders, and its "install" moves
through the real list of steps when ``advance()`` is called."""

from __future__ import annotations

from typing import Any

from agent import __version__, colors

STEPS = [
    "Checking this PC",
    "Copying the program",
    "Saving your settings",
    "Setting up your servers",
    "Making the certificate",
    "Starting the server panel",
    "Checking it answers",
]


class _Thread:
    def __init__(self, alive: bool):
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


class _Result:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.ok = bool(data["ok"])

    def to_dict(self) -> dict[str, Any]:
        return self.data


class DemoWizard:
    def __init__(
        self,
        found: list[dict[str, Any]] | None = None,
        java: bool = True,
        uninstall: bool = False,
        admin: bool = True,
        players_online: int | None = None,
        fail_at: int | None = None,
        older_in: str = "D:\\Apps\\Minecraft Server Controller",
    ):
        self.found = found or []
        self.java_ok = java
        self.uninstall_mode = uninstall
        self.admin = admin
        self.players_online = players_online
        self.fail_at = fail_at
        self.older_in = older_in
        self.started: list[dict[str, Any]] = []
        self.step = -1
        self.thread: _Thread | None = None
        self.result: _Result | None = None
        self.removed: list[bool] = []

    def state(self) -> dict[str, Any]:
        best = {"path": "C:\\Program Files\\Eclipse Adoptium\\jre-21\\bin\\java.exe", "major": 21}
        return {
            "version": __version__,
            "found": self.found,
            "admin": self.admin,
            "program_dir": "C:\\Program Files\\Minecraft Server Controller",
            "data_root": "C:\\ProgramData\\Minecraft Server Controller",
            "palette": colors.palette(),
            "java": {
                "found": [best] if self.java_ok else [{"path": "java", "major": 8}],
                "best": best if self.java_ok else None,
                "needed": 21,
                "install": 21,
            },
            "uninstall": self.uninstall_mode,
            "default_import_to": "C:\\Users\\Mark\\Minecraft Servers",
        }

    def check_folder(self, path: str) -> dict[str, Any]:
        if not path.strip() or "missing" in path.lower():
            return {
                "ok": False,
                "problem": "That folder isn't there. Pick the folder your server is in.",
            }
        name = path.rstrip("\\/").replace("/", "\\").split("\\")[-1]
        return {"ok": True, "folder": path, "type": "fabric", "type_name": "Fabric", "name": name}

    def check_install_folder(self, path: str) -> dict[str, Any]:
        if path.strip().lower() == self.older_in.lower():
            return {"ok": True, "older": True}
        return {"ok": True, "older": False}

    def check_import(self, path: str) -> dict[str, Any]:
        if not path.lower().endswith(".zip"):
            return {
                "ok": False,
                "problem": "That isn't an export file made with Export everything.",
            }
        return {"ok": True, "servers": ["Survival"], "includes": {"secrets": True}}

    def players(self, index: int) -> dict[str, Any]:
        if self.players_online is None:
            return {"known": False, "online": None}
        return {"known": True, "online": self.players_online}

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        self.started.append(body)
        self.step = 0
        self.result = None
        self.thread = _Thread(True)
        return {"ok": True}

    def advance(self, steps: int = 1) -> None:
        self.step += steps
        if self.fail_at is not None and self.step >= self.fail_at:
            self.thread = _Thread(False)
            self.result = _Result(
                {
                    "ok": False,
                    "action": "update",
                    "failed_step": "start",
                    "message": "The new version didn't start.",
                    "details": "The server panel didn't answer on port 8765 within 60 seconds.",
                    "rolled_back": True,
                    "log_path": "C:\\ProgramData\\Minecraft Server Controller\\logs\\install-1.log",
                    "notes": [],
                }
            )
        elif self.step >= len(STEPS):
            self.thread = _Thread(False)
            self.result = _Result(
                {
                    "ok": True,
                    "action": "install",
                    "dashboard_url": "https://mark-pc.tail1234.ts.net:8765",
                    "log_path": "C:\\ProgramData\\Minecraft Server Controller\\logs\\install-1.log",
                    "notes": [],
                }
            )

    def progress(self) -> dict[str, Any]:
        steps = []
        for index, name in enumerate(STEPS):
            if index < self.step:
                state = "done"
            elif index == self.step:
                state = "failed" if self.result and not self.result.ok else "running"
            else:
                state = "waiting"
            steps.append({"name": name, "state": state})
        current = STEPS[min(max(self.step, 0), len(STEPS) - 1)]
        snapshot = {
            "percent": 100.0 * max(self.step, 0) / len(STEPS) + 6.0,
            "indeterminate": self.step == 1,
            "current": current,
            "steps": steps,
        }
        out: dict[str, Any] = {"progress": snapshot, "result": None}
        if self.result is not None:
            out["result"] = self.result.to_dict()
            if self.result.ok:
                url = "https://mark-pc.tail1234.ts.net:8765/?pair=1&fp=" + "ab" * 32 + "&api=1"
                out["pairing"] = {
                    "ok": True,
                    "url": url,
                    "address_url": "https://mark-pc.tail1234.ts.net:8765",
                }
        return out

    def log_text(self) -> str:
        return '{"event": "install_started"}\n'

    def uninstall(self, remove_data: bool) -> dict[str, Any]:
        self.removed.append(remove_data)
        return {
            "ok": True,
            "problems": [],
            "kept": None if remove_data else "C:\\ProgramData\\Minecraft Server Controller",
        }
