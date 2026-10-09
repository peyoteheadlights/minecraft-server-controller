"""The installer's brain, behind its window.

``mcsc.exe setup`` (started by setup.exe) opens the setup window
(``installer/app``, a native Windows app). The window only asks; this class
answers its questions (what is installed already, is this a server folder,
is an older version in that folder, who is playing) and starts
``installer/engine.py`` on a thread of its own, whose real progress the
window shows.

With ``--quiet`` there is no window at all: the engine runs with what the
command line and the found install say (used by CI and by updates started
from the dashboard).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from agent import __version__, appinfo, colors

from . import detect, engine, java_setup, layout
from .detect import Found as FoundInstall
from .installlog import InstallLog
from .system import System


class Wizard:
    """What the screens know and what they asked for."""

    def __init__(self, args: argparse.Namespace, system: System | None = None):
        self.args = args
        self.system = system or System()
        self.data_root = Path(args.data_root) if args.data_root else self._data_root(args)
        self.source_dir = Path(args.source) if args.source else appinfo.program_dir()
        self.found: list[detect.Found] = []
        self.engine: engine.Engine | None = None
        self.result: engine.Result | None = None
        self.snapshot: dict[str, Any] | None = None
        self.thread: threading.Thread | None = None
        self.java: list[java_setup.JavaFound] = []
        self.detect()

    @staticmethod
    def _data_root(args: argparse.Namespace) -> Path:
        """The data folder of the copy named with --program-dir (repair,
        uninstall and updates name it), else the standard one."""
        if args.program_dir:
            record = appinfo.install_record(Path(args.program_dir))
            if record and record.get("data_root"):
                return Path(record["data_root"])
        return layout.data_root()

    # ------------------------------------------------------------ what is here
    def detect(self) -> None:
        probes = detect.probe_windows()
        self.found = detect.find_installs(
            task_folder=probes["task_folder"],
            registry_folder=probes["registry_folder"],
            data_root=self.data_root,
        )
        try:
            self.java = java_setup.find_java()
        except Exception:
            self.java = []

    def state(self) -> dict[str, Any]:
        choices = []
        for found in self.found:
            try:
                action, why = engine.decide_action(found)
                refused = None
            except engine.Refused as exc:
                action, why, refused = "refused", "", exc.message
            choices.append(
                {
                    **found.to_dict(),
                    "describe": found.describe(),
                    "action": action,
                    "why": why,
                    "refused": refused,
                    "servers": self.server_javas(found),
                }
            )
        best = java_setup.best_java(self.java)
        return {
            "version": __version__,
            "found": choices,
            "admin": self.system.is_admin(),
            "program_dir": str(layout.default_program_dir()),
            "data_root": str(self.data_root),
            "palette": colors.palette(),
            "java": {
                "found": [j.to_dict() for j in self.java],
                "best": best.to_dict() if best else None,
                "needed": java_setup.NEWEST_NEEDED,
                "install": java_setup.temurin_major(java_setup.NEWEST_NEEDED),
            },
            "uninstall": bool(self.args.uninstall),
            "default_import_to": str(Path.home() / "Minecraft Servers"),
        }

    def server_javas(self, found: FoundInstall) -> list[dict[str, Any]]:
        """Each server of a found install with the Java it runs on, read by
        running it (``major`` None: it doesn't run). Empty when the settings
        can't be read; the update itself reports that."""
        from agent.config import Config

        try:
            config = Config.load(found.config_path, found.env_path)
            ids = config.server_ids
        except Exception:
            return []
        known = {j.path: j.major for j in self.java}
        out = []
        for server_id in ids:
            settings = config.server_settings(server_id)
            java = settings.java or "java"
            if java not in known:
                known[java] = java_setup.find_java([Path(java)])[0].major
            out.append({"id": server_id, "name": settings.name, "java": java, "major": known[java]})
        return out

    # ------------------------------------------------------------ checks the screens ask for
    def check_folder(self, path: str) -> dict[str, Any]:
        from .servers import describe_folder

        return describe_folder(path, protected=[layout.default_program_dir(), self.data_root])

    def check_install_folder(self, path: str) -> dict[str, Any]:
        """For the Advanced folder field: is an older version already there?"""
        folder = Path(path.strip().strip('"'))
        if not folder.is_absolute():
            return {"ok": False, "problem": "Enter the whole path, for example C:\\Apps."}
        found = detect.classify(folder)
        if found is None:
            return {"ok": True, "older": False}
        verdict = layout.compare_versions(__version__, found.version)
        return {
            "ok": verdict != "older",
            "older": verdict in ("newer", "unknown"),
            "same": verdict == "same",
            "found": found.to_dict(),
            "problem": None
            if verdict != "older"
            else f"A newer version ({found.version}) is installed there, so it can't be replaced.",
        }

    def check_import(self, path: str) -> dict[str, Any]:
        from agent.transfer import TransferError, read_manifest

        try:
            manifest = read_manifest(Path(path.strip().strip('"')))
        except (TransferError, OSError) as exc:
            return {"ok": False, "problem": str(exc)}
        return {
            "ok": True,
            "servers": [s.get("name") for s in manifest.get("servers", [])],
            "includes": manifest.get("includes", {}),
        }

    def players(self, index: int) -> dict[str, Any]:
        """Who is playing on the copy about to be updated, from the app itself."""
        found = self.found[index]
        from .setup_tool import read_env

        token = read_env(found.env_path).get("MCSC_API_TOKEN", "")
        port, tls = 8765, True
        try:
            import yaml

            data = yaml.safe_load(found.config_path.read_text(encoding="utf-8")) or {}
            port = int((data.get("network") or {}).get("port") or port)
            tls = bool((data.get("tls") or {}).get("enabled", True))
        except Exception:
            pass
        if not token or not self.system.agent_answers(port, tls):
            return {"known": False, "online": None, "running": 0}
        try:
            rows = self.system.api(port, tls, token, "GET", "/servers")["servers"]
        except Exception:
            # The app answers but wouldn't list its servers: one may be
            # running with people on it, so ask rather than assume.
            return {"known": False, "online": None, "running": None}
        counts = [r.get("players_online") for r in rows if r.get("state") == "running"]
        if any(c is None for c in counts):
            return {"known": False, "online": None, "running": len(counts)}
        return {"known": True, "online": sum(counts), "running": len(counts)}

    # ------------------------------------------------------------ the work
    def choices_from(self, body: dict[str, Any]) -> engine.Choices:
        index = body.get("found")
        found = self.found[int(index)] if index is not None and self.found else None
        program_dir = Path(body.get("program_dir") or layout.default_program_dir())
        if found is not None and found.kind == detect.INSTALLER:
            program_dir = found.program_dir
        try:
            action = engine.decide_action(found)[0]
        except engine.Refused:
            action = engine.UPDATE  # the engine refuses it again, before changing anything
        install_java = body.get("install_java")
        return engine.Choices(
            action=action,
            program_dir=program_dir,
            data_root=found.data_root if found and found.data_root else self.data_root,
            found=found,
            servers=[s for s in body.get("servers", []) if s.get("folder")],
            password=body.get("password") or None,
            start_with_pc=bool(body.get("start_with_pc", True)),
            allow_devices=bool(body.get("allow_devices", True)),
            phone_alerts=bool(body.get("phone_alerts", False)),
            push_contact=str(body.get("push_contact") or ""),
            import_file=Path(body["import_file"]) if body.get("import_file") else None,
            import_to=Path(body["import_to"]) if body.get("import_to") else None,
            import_passphrase=body.get("import_passphrase") or None,
            java_path=body.get("java_path") or None,
            install_java=int(install_java) if install_java else None,
            java_servers=[str(i) for i in body.get("java_servers") or []],
            setup_exe=Path(self.args.setup_exe) if self.args.setup_exe else None,
            from_app=bool(self.args.from_app),
        )

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.thread and self.thread.is_alive():
            return {"ok": False, "problem": "It's already running."}
        choices = self.choices_from(body)
        log = InstallLog(layout.logs_dir(choices.data_root))
        self.result = None
        self.engine = engine.Engine(
            choices, self.source_dir, self.system, log, on_progress=self._on_progress
        )
        self.snapshot = self.engine.progress.snapshot()

        def work() -> None:
            assert self.engine is not None
            self.result = self.engine.run()

        self.thread = threading.Thread(target=work, name="install", daemon=True)
        self.thread.start()
        return {"ok": True}

    def _on_progress(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot

    def progress(self) -> dict[str, Any]:
        out: dict[str, Any] = {"progress": self.snapshot, "result": None}
        if self.result is not None:
            out["result"] = self.result.to_dict()
            if self.result.ok:
                out["pairing"] = self._pairing()
        return out

    def _pairing(self) -> dict[str, Any] | None:
        try:
            from agent.config import Config
            from agent.pairing import pairing_code

            assert self.engine is not None
            config = Config.load(self.engine.config_path, self.engine.env_path)
            return pairing_code(config)
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def log_text(self) -> str:
        if self.engine is None:
            return ""
        return self.engine.log.text()

    # ------------------------------------------------------------ uninstall
    def uninstall(self, remove_data: bool) -> dict[str, Any]:
        from .uninstall import uninstall

        return uninstall(
            Path(self.args.program_dir or appinfo.program_dir()),
            self.data_root,
            remove_data=remove_data,
            system=self.system,
        )


# ====================================================================
# quiet: no screens
# ====================================================================
def quiet(wizard: Wizard) -> int:
    args = wizard.args
    if args.uninstall:
        result = wizard.uninstall(remove_data=args.remove_data)
        _write_result(args, result)
        return 0 if result.get("ok") else 1
    index = 0 if wizard.found else None
    if args.program_dir and wizard.found:
        wanted = os.path.normcase(str(Path(args.program_dir)))
        index = next(
            (
                i
                for i, f in enumerate(wizard.found)
                if os.path.normcase(str(f.program_dir)) == wanted
            ),
            index,
        )
    body: dict[str, Any] = {
        "found": index,
        "program_dir": args.program_dir,
        "password": os.environ.get(args.password_env) if args.password_env else None,
        "start_with_pc": not args.no_startup,
        "allow_devices": not args.no_firewall,
        "servers": [{"folder": f, "name": Path(f).name} for f in args.server_folder or []],
        "java_path": args.java,
    }
    wizard.start(body)
    assert wizard.thread is not None
    wizard.thread.join()
    assert wizard.result is not None
    result = wizard.result.to_dict()
    _write_result(args, result)
    print(json.dumps({k: result[k] for k in ("ok", "action", "failed_step", "message")}))
    return 0 if wizard.result.ok else 1


def _write_result(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.result_file:
        Path(args.result_file).write_text(json.dumps(result, indent=2, default=str), "utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="setup", description="Install or update the app.")
    parser.add_argument("--quiet", action="store_true", help="no screens (automation, updates)")
    parser.add_argument("--update", action="store_true", help="update the copy that's installed")
    parser.add_argument("--from-app", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--remove-data", action="store_true", help="with --uninstall")
    parser.add_argument("--program-dir", help="where to install (Advanced)")
    parser.add_argument("--data-root", help=argparse.SUPPRESS)
    parser.add_argument("--source", help=argparse.SUPPRESS)
    parser.add_argument("--setup-exe", help=argparse.SUPPRESS)
    parser.add_argument("--server-folder", action="append", help="with --quiet")
    parser.add_argument("--java", help="with --quiet: the java.exe for the servers")
    parser.add_argument(
        "--password-env",
        help="with --quiet: the environment variable holding the password "
        "(never put a password on a command line)",
    )
    parser.add_argument("--no-startup", action="store_true")
    parser.add_argument("--no-firewall", action="store_true")
    parser.add_argument("--result-file", help="write the outcome here as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    wizard = Wizard(args)
    if args.quiet:
        return quiet(wizard)
    from .app.window import run

    return run(wizard)


if __name__ == "__main__":
    sys.exit(main())
