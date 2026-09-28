"""Drive the real dashboard in headless Chromium.

Starts the actual agent (with the fake Minecraft server from the test suite),
signs in through the real login form, visits every page at several window
sizes in light and dark mode, and records:

  * screenshots
  * JavaScript console errors and uncaught exceptions
  * horizontal overflow (content wider than the window)
  * failed network requests

Usage:  python scripts/ui_check.py [output_dir] [--quick]
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.security.auth import hash_password  # noqa: E402

PASSWORD = "screenshot password 1"
SIZES = [(1920, 1080), (1440, 900), (1280, 720), (1024, 700), (390, 844)]
PAGES = ["dashboard", "console", "players", "performance", "backups", "mods",
         "schedules", "events", "crashes", "settings", "security"]


def start_agent(tmp: Path):
    mc = tmp / "Minecraft Server"
    for sub in ("mods", "config", "world", "world_nether", "world_the_end", "logs", "crash-reports"):
        (mc / sub).mkdir(parents=True, exist_ok=True)
    (mc / "world" / "level.dat").write_bytes(b"x" * 4096)
    (mc / "server.properties").write_text("server-port=25565\n")
    # a mod with a dependency that is not installed, as SkinsRestorer/cloud was
    import json as _json, zipfile as _zip
    with _zip.ZipFile(mc / "mods" / "skinsrestorer.jar", "w") as zf:
        zf.writestr("fabric.mod.json", _json.dumps({"schemaVersion": 1, "id": "skinsrestorer",
                    "name": "SkinsRestorer", "version": "15.0", "depends": {"cloud": "*"}}))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = {
        "server": {"id": "ui", "name": "Survival", "directory": str(mc),
                   "raw_command": [sys.executable, str(ROOT / "tests/fixtures/fake_server.py")],
                   "max_players": 20},
        "paths": {"data_dir": str(tmp / "data")},
        "network": {"host": "127.0.0.1", "port": port},
        "tls": {"enabled": False},
        "monitor": {"auto_restart": True, "restart_delay": 5, "sample_interval": 2,
                    "tps_command": "auto"},
    }
    cfg = tmp / "config.yaml"
    cfg.write_text(yaml.safe_dump(config))
    env = dict(os.environ,
               MCSC_ADMIN_USERNAME="admin",
               MCSC_ADMIN_PASSWORD_HASH=hash_password(PASSWORD, rounds=1000),
               MCSC_STARTUP_LOG_DIR=str(tmp / "startup-logs"),
               FAKE_STOP_DELAY="2", FAKE_BOOT_DELAY="1.5")
    env.pop("MCSC_API_TOKEN", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent.main", "--config", str(cfg), "--no-tls"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("agent did not start")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "ui-shots")
    quick = "--quick" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="mcsc-ui-"))
    proc, base = start_agent(tmp)
    report = {"errors": [], "overflow": [], "failed_requests": [], "shots": []}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in (["light"] if quick else ["light", "dark"]):
                context = browser.new_context(viewport={"width": 1440, "height": 900},
                                              color_scheme=scheme, device_scale_factor=1)
                page = context.new_page()
                page.on("console", lambda m, s=scheme: m.type == "error" and
                        report["errors"].append(f"[{s}] console: {m.text}"))
                page.on("pageerror", lambda e, s=scheme: report["errors"].append(f"[{s}] {e}"))
                page.on("requestfailed", lambda r: report["failed_requests"].append(
                    f"{r.method} {r.url} {r.failure}"))

                page.goto(base + "/")
                page.fill("#username", "admin")
                page.fill("#password", PASSWORD)
                page.click("#login-form button[type=submit]")
                page.wait_for_timeout(1200)

                if scheme == "light":
                    # bring the server up so pages show real, live data
                    token = page.evaluate("sessionStorage.getItem('mcsc_token')")
                    auth = {"Authorization": f"Bearer {token}"}
                    httpx.post(f"{base}/api/server/start", headers=auth)
                    for _ in range(60):
                        if httpx.get(f"{base}/api/status", headers=auth).json()["state"] == "ONLINE":
                            break
                        time.sleep(0.25)
                    for cmd in ("fakejoin Steve", "fakejoin Alex", "tps"):
                        httpx.post(f"{base}/api/server/command", headers=auth, json={"command": cmd})
                    httpx.post(f"{base}/api/backups", headers=auth, json={})
                    time.sleep(1.5)

                sizes = [(1440, 900)] if quick else SIZES
                for width, height in sizes:
                    page.set_viewport_size({"width": width, "height": height})
                    for name in PAGES:
                        page.evaluate(f"location.hash = '{name}'")
                        page.wait_for_timeout(700)
                        overflow = page.evaluate(
                            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)"
                            " - window.innerWidth")
                        if overflow > 1:
                            report["overflow"].append(f"{scheme} {width}x{height} {name}: +{overflow}px")
                        if width in (1440, 390) or name == "dashboard":
                            path = out / f"{scheme}-{width}-{name}.png"
                            page.screenshot(path=str(path), full_page=False)
                            report["shots"].append(path.name)
                context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()

    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(f"screenshots: {len(report['shots'])} in {out}")
    print(f"javascript errors: {len(report['errors'])}")
    for e in report["errors"][:15]:
        print("   ", e)
    print(f"horizontal overflow: {len(report['overflow'])}")
    for o in report["overflow"][:25]:
        print("   ", o)
    print(f"failed requests: {len(report['failed_requests'])}")
    for r in report["failed_requests"][:10]:
        print("   ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
