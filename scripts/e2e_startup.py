"""Simulate a Windows startup launch as closely as a non-Windows machine can.

What is reproduced faithfully:
  * the exact command the scheduled task runs: `-m agent.main --launched-by task`
  * working directory set to the project folder, as the task sets it
  * no console: stdin/stdout/stderr are closed and sys.stdout/sys.stderr are
    None inside the process, exactly as under pythonw.exe
  * a stripped-down PATH, as a startup context may have
  * the Tailscale boot race: the address the agent binds to does NOT exist
    when the agent starts, and is added a few seconds later
  * success is judged only from logs/startup.log and the network, because a
    startup launch has no console to read

What cannot be reproduced here: Task Scheduler itself and a real reboot.
Those are the steps in the manual checklist.

Linux only (it adds a loopback alias). Run as root.
"""

import fcntl
import json
import os
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.security.auth import hash_password  # noqa: E402
from agent.security.certs import issue_server_certificate  # noqa: E402

LATE_ADDRESS = "203.0.113.250"     # documentation range: never assigned by default
ALIAS = b"lo:9"
PASSWORD = "startup simulation password"
RESULTS = []


def step(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def set_alias(address: str | None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if address:
        req = struct.pack("16sH2s4s8s", ALIAS, socket.AF_INET, b"\0" * 2,
                          socket.inet_aton(address), b"\0" * 8)
        fcntl.ioctl(s.fileno(), 0x8916, req)          # SIOCSIFADDR
    else:
        try:
            flags = struct.unpack("16sh", fcntl.ioctl(s.fileno(), 0x8913,
                                                      struct.pack("16sh", ALIAS, 0)))[1]
            fcntl.ioctl(s.fileno(), 0x8914, struct.pack("16sh", ALIAS, flags & ~1))  # down
        except OSError:
            pass


def bindable(address):
    try:
        with socket.socket() as probe:
            probe.bind((address, 0))
        return True
    except OSError:
        return False


def events(log_dir):
    path = log_dir / "startup.log"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    set_alias(None)
    step("Bind address does not exist before launch (boot race set up)", not bindable(LATE_ADDRESS))

    tmp = Path(tempfile.mkdtemp(prefix="mcsc-startup-"))
    log_dir = tmp / "startup-logs"
    mc = tmp / "Minecraft Server"
    for sub in ("mods", "config", "world", "logs", "crash-reports"):
        (mc / sub).mkdir(parents=True, exist_ok=True)
    (mc / "world" / "level.dat").write_bytes(b"x" * 1024)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    data_dir = tmp / "data"
    cert = issue_server_certificate(data_dir / "certs", ["localhost"], [LATE_ADDRESS, "127.0.0.1"])
    config = {
        "server": {"id": "boot", "name": "Boot test", "directory": str(mc),
                   "raw_command": [sys.executable, str(ROOT / "tests/fixtures/fake_server.py")],
                   "autostart_minecraft": True},
        "paths": {"data_dir": str(data_dir)},
        "network": {"host": LATE_ADDRESS, "port": port, "bind_wait_seconds": 120},
        "monitor": {"auto_restart": True, "restart_delay": 0.5},
        "tls": {"enabled": True, "certificate": cert["cert_path"], "private_key": cert["key_path"],
                "ca_certificate": cert["ca_path"], "hostname": LATE_ADDRESS, "http_redirect": False},
        "notifications": {"discord_enabled": True},
    }
    cfg_file = tmp / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(config))

    env = {
        # a deliberately minimal environment, like a startup context
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp),
        "MCSC_STARTUP_LOG_DIR": str(log_dir),
        "MCSC_ADMIN_USERNAME": "admin",
        "MCSC_ADMIN_PASSWORD_HASH": hash_password(PASSWORD, rounds=1000),
        "MCSC_DISCORD_WEBHOOK": "https://127.0.0.1:9/unreachable-webhook",
    }
    # pythonw.exe equivalent: the interpreter starts with sys.stdout/stderr = None
    launcher = (
        "import sys, runpy\n"
        "sys.stdout = None\n"
        "sys.stderr = None\n"
        f"sys.argv = ['agent.main', '--launched-by', 'task', '--config', {str(cfg_file)!r}]\n"
        "runpy.run_module('agent.main', run_name='__main__', alter_sys=True)\n"
    )

    print("\n=== Launch exactly as the startup task does ===")
    proc = subprocess.Popen([sys.executable, "-c", launcher], cwd=str(ROOT), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    ca = cert["ca_path"]
    base = f"https://{LATE_ADDRESS}:{port}"

    try:
        time.sleep(6)
        log = events(log_dir)
        names = [e["event"] for e in log]
        step("Process is still alive while the address is missing", proc.poll() is None)
        step("Startup log written with no console attached", bool(log), f"{len(log)} events")
        first = log[0] if log else {}
        step("Log records launch source = task", first.get("launched_by") == "task")
        step("Log records the executable", first.get("executable") == sys.executable,
             first.get("executable", ""))
        step("Log records the working directory = project folder",
             first.get("cwd") == str(ROOT), first.get("cwd", ""))
        step("Log records the command-line arguments", "--launched-by" in first.get("argv", []))
        step("Log shows it is waiting for the bind address", "bind_address_waiting" in names,
             next((e.get("error", "") for e in log if e["event"] == "bind_address_waiting"), ""))

        print("\n=== The address appears (Tailscale finishes connecting) ===")
        set_alias(LATE_ADDRESS)
        up = False
        for _ in range(120):
            time.sleep(0.5)
            try:
                with httpx.Client(verify=ca, timeout=3) as client:
                    if client.get(f"{base}/api/health").status_code == 200:
                        up = True
                        break
            except httpx.HTTPError:
                continue
        step("Agent bound as soon as the address appeared, over verified HTTPS", up)
        names = [e["event"] for e in events(log_dir)]
        step("Log shows bind_address_available", "bind_address_available" in names)
        step("Log shows controller_initialized", "controller_initialized" in names)
        step("No exception was logged",
             not any(n in ("exception", "unhandled_exception") for n in names))
        console = log_dir / "console.log"
        step("Console output captured to console.log instead of being lost", console.is_file())

        print("\n=== The controller actually works when started this way ===")
        with httpx.Client(verify=ca, timeout=15) as client:
            token = client.post(f"{base}/api/auth/login",
                                json={"username": "admin", "password": PASSWORD}).json()["token"]
            auth = {"Authorization": f"Bearer {token}"}
            online = False
            for _ in range(80):
                time.sleep(0.25)
                status = client.get(f"{base}/api/status", headers=auth).json()
                if status["state"] == "ONLINE":
                    online = True
                    break
            step("autostart_minecraft started Minecraft with nobody logged in", online,
                 status.get("state"))
            client.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            crashed = recovered = False
            for _ in range(200):
                time.sleep(0.25)
                state = client.get(f"{base}/api/status", headers=auth).json()["state"]
                crashed = crashed or state in ("CRASHED", "RESTART_PENDING")
                if crashed and state == "ONLINE":
                    recovered = True
                    break
            step("Crash detected", crashed)
            step("Automatic restart recovered the server", recovered)
            history = client.get(f"{base}/api/notifications/history", headers=auth).json()["history"]
            step("Notification attempted and its failure recorded (agent unaffected)",
                 any(h["status"] == "failed" for h in history))
            step("Agent still running after the notification failure", proc.poll() is None)

        print("\n=== Clean shutdown ===")
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            code = None
        last = json.loads((log_dir / "last_startup.json").read_text())
        step("Agent shut down on request", code is not None, f"exit code {code}")
        step("Startup record closed with an outcome",
             last.get("outcome") in ("stopped", "exited"), last.get("outcome"))
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        set_alias(None)

    passed = sum(ok for _, ok in RESULTS)
    print("\n" + "=" * 62)
    print(f"STARTUP SIMULATION: {passed}/{len(RESULTS)} checks passed")
    print(f"Startup log kept at: {log_dir / 'startup.log'}")
    print("=" * 62)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
