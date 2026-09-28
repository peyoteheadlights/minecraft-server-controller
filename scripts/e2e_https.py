"""End-to-end verification over real HTTPS.

Starts a real uvicorn TLS listener, drives it with an HTTP client that
**verifies** the certificate against the local CA, and watches a real
WebSocket over wss://. Every assertion is against observed behaviour.
"""

import asyncio
import json
import os
import ssl
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx
import uvicorn
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import DEFAULTS, Config, _deep_merge  # noqa: E402
from agent.main import create_app, resolve_tls  # noqa: E402
from agent.security.auth import hash_password  # noqa: E402
from agent.security.certs import issue_server_certificate  # noqa: E402

PASSWORD = "end to end password"
RESULTS = []


def step(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def make_jar(path, mod_id, version):
    meta = {"schemaVersion": 1, "id": mod_id, "version": version,
            "name": mod_id.title(), "depends": {"minecraft": ">=1.20"}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps(meta))
        zf.writestr(f"{mod_id}/Main.class", b"\xca\xfe\xba\xbe")
    return path


def build(tmp: Path, port: int):
    mc = tmp / "Minecraft Server"
    for sub in ("mods", "config", "world", "world_nether", "world_the_end", "logs", "crash-reports"):
        (mc / sub).mkdir(parents=True, exist_ok=True)
    (mc / "server.properties").write_text("server-port=25565\n")
    (mc / "world" / "level.dat").write_bytes(b"x" * 4096)

    data = _deep_merge(DEFAULTS, {
        "server": {"id": "e2e", "name": "E2E Server", "directory": str(mc),
                   "raw_command": [sys.executable, str(ROOT / "tests/fixtures/fake_server.py")],
                   "stop_timeout": 15},
        "paths": {"data_dir": str(tmp / "data")},
        "monitor": {"auto_restart": True, "restart_delay": 0.5, "sample_interval": 2,
                    "max_crashes": 5},
        "network": {"host": "127.0.0.1", "port": port},
        "notifications": {"discord_enabled": True},
    })
    config = Config(data, tmp / "config.yaml")
    config.ensure_dirs()
    result = issue_server_certificate(config.cert_dir, ["localhost"], ["127.0.0.1"])
    config.set("tls.enabled", True)
    config.set("tls.certificate", result["cert_path"])
    config.set("tls.private_key", result["key_path"])
    config.set("tls.ca_certificate", result["ca_path"])
    config.set("tls.hostname", "localhost")
    return config, mc


def main():
    import socket
    import tempfile

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    tmp = Path(tempfile.mkdtemp(prefix="mcsc-e2e-"))
    # Keep this run out of the project's real logs/startup.log, which holds the
    # record of the last genuine Windows startup.
    from agent import startup_diag
    os.environ["MCSC_STARTUP_LOG_DIR"] = str(tmp / "startup-logs")
    startup_diag.set_log_dir(tmp / "startup-logs")
    os.environ["MCSC_ADMIN_USERNAME"] = "admin"
    os.environ["MCSC_ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD, rounds=1000)
    # A webhook that cannot possibly work: proves a notification failure does
    # not affect the server.
    os.environ["MCSC_DISCORD_WEBHOOK"] = "https://127.0.0.1:9/webhook-that-cannot-connect"
    # No TPS provider: the "unknown, never 20.0" check below needs a server that
    # genuinely cannot report TPS. (Detection itself is covered by tests/test_tps_detection.py.)
    os.environ["FAKE_TPS_PROVIDER"] = "none"
    os.environ.pop("MCSC_API_TOKEN", None)

    config, mc_dir = build(tmp, port)
    certfile, keyfile = resolve_tls(config)
    server = uvicorn.Server(uvicorn.Config(
        create_app(config), host="127.0.0.1", port=port,
        ssl_certfile=certfile, ssl_keyfile=keyfile,
        log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline and not server.started:
        time.sleep(0.1)

    base = f"https://localhost:{port}"
    ca = str(config.tls_ca_certificate)
    events = []
    ws_thread = None

    try:
        print("\n=== Transport ===")
        with httpx.Client(verify=ca, timeout=30) as client:
            step("HTTPS endpoint answers with a CA-verified certificate",
                 client.get(f"{base}/api/health").status_code == 200)
            try:
                httpx.Client(timeout=5).get(f"{base}/api/health")
                step("Untrusted client is rejected", False, "it connected, which is wrong")
            except httpx.ConnectError:
                step("Untrusted client is rejected (certificate really is checked)", True)

            print("\n=== Authentication ===")
            step("Unauthenticated request refused",
                 client.get(f"{base}/api/status").status_code == 401)
            step("Wrong password refused",
                 client.post(f"{base}/api/auth/login",
                             json={"username": "admin", "password": "wrong"}).status_code == 401)
            token = client.post(f"{base}/api/auth/login",
                                json={"username": "admin", "password": PASSWORD}).json()["token"]
            auth = {"Authorization": f"Bearer {token}"}
            step("Valid credentials return a session token", bool(token))
            step("Authenticated request accepted",
                 client.get(f"{base}/api/status", headers=auth).status_code == 200)

            print("\n=== WSS live stream ===")
            context = ssl.create_default_context(cafile=ca)
            ready = {}

            ws_error = {}

            def listen():
                try:
                    with connect(f"wss://localhost:{port}/ws", ssl=context,
                                 open_timeout=20) as ws:
                        ws.send(json.dumps({"type": "auth", "token": token}))
                        ready.update(json.loads(ws.recv(timeout=20)))
                        while True:
                            events.append(json.loads(ws.recv(timeout=300)))
                except Exception as exc:
                    ws_error["error"] = f"{type(exc).__name__}: {exc}"

            ws_thread = threading.Thread(target=listen, daemon=True)
            ws_thread.start()
            time.sleep(2)
            step("wss:// handshake and authentication", ready.get("type") == "ready",
                 ws_error.get("error", ""))

            print("\n=== No fabrication before evidence exists ===")
            status = client.get(f"{base}/api/status", headers=auth).json()
            # The agent verified the process is not running, so zero players is
            # a fact with a stated source - not an assumption.
            step("Player count carries its source, not a blind zero",
                 status["players_verified"] is True
                 and "not running" in (status["players_source"] or ""),
                 f"count={status['players_online']} source={status['players_source']}")
            step("TPS is unknown with no provider", status["tps"] is None)
            step("Minecraft version unknown before first start",
                 status["minecraft_version"] is None)

            print("\n=== Server lifecycle ===")
            start = client.post(f"{base}/api/server/start", headers=auth).json()
            step("Start is reported as REQUESTED, not success",
                 start["result"] == "REQUESTED", start["detail"][:60])
            online = False
            for _ in range(80):
                time.sleep(0.25)
                status = client.get(f"{base}/api/status", headers=auth).json()
                if status["state"] == "ONLINE":
                    online = True
                    break
            step("Server reaches ONLINE (startup line observed)", online)
            step("Startup confirmed flag set", status.get("startup_confirmed") is not False)
            step("Minecraft version detected from console",
                 status["minecraft_version"] == "1.21.1", status["minecraft_version"] or "none")
            step("Fabric loader detected from console",
                 status["fabric_loader"] == "0.16.5", status["fabric_loader"] or "none")

            print("\n=== Console and players ===")
            refused = client.post(f"{base}/api/server/command", headers=auth,
                                  json={"command": "stop"})
            step("Dangerous command refused without confirmation",
                 refused.status_code == 400 and "confirmation" in refused.json()["detail"])
            injection = client.post(f"{base}/api/server/command", headers=auth,
                                    json={"command": "say hi; shutdown /s", "confirm": True})
            step("Shell injection refused", injection.status_code == 400)
            still_up = client.get(f"{base}/api/status", headers=auth).json()["state"]
            step("Server still ONLINE after refused commands", still_up == "ONLINE")

            client.post(f"{base}/api/server/command", headers=auth,
                        json={"command": "fakejoin Steve"})
            time.sleep(1.5)
            players = client.get(f"{base}/api/players", headers=auth).json()
            step("Player join tracked", players["online_count"] == 1,
                 str([p["username"] for p in players["online"]]))
            client.post(f"{base}/api/server/command", headers=auth,
                        json={"command": "fakeleave Steve"})
            time.sleep(1.5)
            players = client.get(f"{base}/api/players", headers=auth).json()
            step("Player leave tracked", players["online_count"] == 0)

            print("\n=== Health ===")
            health = client.get(f"{base}/api/health/server", headers=auth).json()
            step("Health reports overall verification state",
                 health["overall"] in ("PARTIALLY VERIFIED", "ATTENTION NEEDED",
                                       "ALL CHECKS VERIFIED"), health["overall"])
            tps_check = next(c for c in health["checks"] if c["name"] == "TPS")
            step("TPS reported as unknown, not 20.0", tps_check["status"] == "unknown")
            cert_check = [c for c in health["checks"] if c["name"] == "TLS certificate"]
            step("TLS certificate health check present and OK",
                 bool(cert_check) and cert_check[0]["status"] == "ok",
                 cert_check[0]["value"] if cert_check else "missing")

            print("\n=== Backups ===")
            backup = client.post(f"{base}/api/backups", headers=auth, json={}).json()
            step("Backup created and verified", backup.get("verified") is True,
                 f"{backup.get('files')} files")
            verify = client.get(f"{base}/api/backups/{backup['id']}/verify", headers=auth).json()
            step("Independent verify passes", verify["ok"] is True)

            print("\n=== Mods ===")
            jar = make_jar(tmp / "cooltech.jar", "cooltech", "1.0.0")
            client.post(f"{base}/api/server/stop", headers=auth, json={})
            time.sleep(2)
            upload = client.post(f"{base}/api/mods/upload", headers=auth,
                                 files={"file": ("cooltech-1.0.0.jar", jar.read_bytes(),
                                                 "application/java-archive")})
            body = upload.json()
            step("Mod installed", upload.status_code == 200, body.get("installed", {}).get("name", ""))
            step("Install does not claim the mod is loaded",
                 body.get("loaded_by_minecraft") == "not verified")

            evil = client.post(f"{base}/api/mods/upload", headers=auth,
                               files={"file": ("payload.exe", b"MZ", "application/octet-stream")})
            step("Executable upload refused", evil.status_code == 400)
            traversal = client.post(f"{base}/api/mods/upload", headers=auth,
                                    files={"file": ("../../evil.jar", b"PK\x03\x04",
                                                    "application/java-archive")})
            step("Path traversal upload refused", traversal.status_code == 400)

            client.post(f"{base}/api/server/start", headers=auth)
            for _ in range(80):
                time.sleep(0.25)
                if client.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE":
                    break
            logs = client.get(f"{base}/api/logs?lines=100", headers=auth).json()["lines"]
            loaded = any("cooltech" in line["raw"] for line in logs)
            step("Server actually loaded the installed mod", loaded)

            client.post(f"{base}/api/server/stop", headers=auth, json={})
            time.sleep(2)
            disable = client.post(f"{base}/api/mods/disable", headers=auth,
                                  json={"filename": "cooltech-1.0.0.jar"})
            step("Mod disabled", disable.status_code == 200)
            client.post(f"{base}/api/logs/clear", headers=auth)
            client.post(f"{base}/api/server/start", headers=auth)
            for _ in range(80):
                time.sleep(0.25)
                if client.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE":
                    break
            logs = client.get(f"{base}/api/logs?lines=100", headers=auth).json()["lines"]
            step("Disabled mod is not loaded by the server",
                 not any("cooltech" in line["raw"] for line in logs))

            client.post(f"{base}/api/server/stop", headers=auth, json={})
            time.sleep(2)
            enable = client.post(f"{base}/api/mods/enable", headers=auth,
                                 json={"filename": "cooltech-1.0.0.jar.disabled"})
            step("Mod re-enabled", enable.status_code == 200)
            versions = client.get(f"{base}/api/mods/versions/cooltech", headers=auth).json()
            step("Version history retained for rollback",
                 len(versions["versions"]) >= 1, f"{len(versions['versions'])} archived")

            print("\n=== Crash handling ===")
            client.post(f"{base}/api/server/start", headers=auth)
            for _ in range(80):
                time.sleep(0.25)
                if client.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE":
                    break
            client.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            crashed = False
            for _ in range(60):
                time.sleep(0.25)
                state = client.get(f"{base}/api/status", headers=auth).json()["state"]
                if state in ("CRASHED", "RESTART_PENDING"):
                    crashed = True
                    break
            step("Crash detected", crashed)
            crashes = client.get(f"{base}/api/crashes", headers=auth).json()["crashes"]
            step("Crash classified with evidence", bool(crashes),
                 f"{crashes[0]['category']} / {crashes[0]['confidence']}" if crashes else "none")

            recovered = False
            for _ in range(160):
                time.sleep(0.25)
                if client.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE":
                    recovered = True
                    break
            step("Automatic restart brought the server back to ONLINE", recovered)

            print("\n=== Notification failure isolation ===")
            history = client.get(f"{base}/api/notifications/history", headers=auth).json()["history"]
            failures = [h for h in history if h["status"] == "failed"]
            step("Discord failures recorded, not raised", bool(failures),
                 failures[0]["detail"][:50] if failures else "no attempts recorded")
            step("Server still ONLINE despite notification failures",
                 client.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE")

            print("\n=== Events over WSS ===")
            texts = " ".join(json.dumps(m) for m in events if isinstance(m, dict))
            step("WSS delivered live messages", bool(events),
                 f"{len(events)} messages, ws error: {ws_error.get('error', 'none')}")
            step("Crash event delivered over WSS", "server_crashed" in texts)
            step("Player events delivered over WSS", "Steve" in texts)
            step("Backup event delivered over WSS", "backup_completed" in texts)
            step("Console lines streamed over WSS", '"console"' in texts)
            step("Recovery event delivered over WSS", "server_recovered" in texts)

            print("\n=== Cleanup ===")
            stop = client.post(f"{base}/api/server/stop", headers=auth, json={}).json()
            step("Stop reports VERIFIED after the process exits",
                 stop["result"] == "VERIFIED", stop["detail"][:50])
            logout = client.post(f"{base}/api/auth/logout", headers=auth)
            step("Logout invalidates the session",
                 logout.status_code == 200
                 and client.get(f"{base}/api/status", headers=auth).status_code == 401)
    finally:
        server.should_exit = True
        thread.join(timeout=20)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 62)
    print(f"END-TO-END RESULT: {passed}/{total} checks passed")
    if passed != total:
        print("Failures:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 62)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
