"""Install, use and remove the built installer on a clean Windows PC, with
no window (run by the "Installer" job in .github/workflows/ci.yml).

    python scripts/installer_smoke.py dist/MinecraftServerController-Setup-1.2.0.exe

1. Runs the setup with ``--quiet``, the password given through an
   environment variable (``--password-env``), never on the command line.
2. Checks the agent it started answers: ``/api/health``, then signing in with
   that password and ``/api/version``.
3. Looks for the password in everything the setup wrote or printed (the
   result, the install logs, the settings): it must be nowhere.
4. Removes the app with the copy of the setup kept in the program folder,
   ``--remove-data`` included, and checks the program folder, the Start menu
   folder and the startup task are gone.

Changes this PC (it is for a throwaway CI machine): refuses to run unless
``CI`` is set.
"""

from __future__ import annotations

import json
import os
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fail(text: str) -> None:
    print(f"::error::{text}")
    raise SystemExit(1)


def call(url: str, token: str | None = None, body: dict | None = None) -> dict:
    # The certificate is the installer's own (no Tailscale on CI), so it isn't
    # checked here; the agent's TLS is covered by its own tests.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20, context=context) as answer:
        return json.loads(answer.read().decode())


def wait_for(url: str, seconds: int = 90) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        try:
            return call(url)
        except OSError as exc:
            if time.monotonic() > deadline:
                fail(f"{url} didn't answer within {seconds} s: {exc}")
            time.sleep(2)


def files_under(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file()] if folder.is_dir() else []


def main() -> int:
    if not os.environ.get("CI") or os.name != "nt":
        print("This installs and removes the app: it runs on a Windows CI machine only.")
        return 2
    from installer import layout

    setup = Path(sys.argv[1]).resolve()
    password = "ci-" + secrets.token_urlsafe(18)
    work = Path(tempfile.mkdtemp(prefix="mcsc-smoke-"))
    result_file = work / "install.json"
    env = {**os.environ, "MCSC_CI_PASSWORD": password}

    print(f"installing {setup.name}")
    done = subprocess.run(
        [
            str(setup),
            "--quiet",
            "--password-env",
            "MCSC_CI_PASSWORD",
            "--result-file",
            str(result_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    printed = done.stdout + done.stderr
    print(printed)
    if not result_file.is_file():
        fail(f"The setup wrote no result (exit {done.returncode}).")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if done.returncode != 0 or not result.get("ok"):
        fail(f"The install failed at {result.get('failed_step')}: {result.get('message')}")
    url = result.get("dashboard_url")
    if not url:
        fail("The result names no dashboard address.")
    print(f"installed; the dashboard is at {url}")

    health = wait_for(url.rstrip("/") + "/api/health")
    if not health.get("ok") or not isinstance(health.get("api_version"), int):
        fail(f"/api/health answered {health}")
    login = call(
        url.rstrip("/") + "/api/auth/login",
        body={"username": "admin", "password": password, "label": "CI"},
    )
    token = login.get("token")
    if not token:
        fail("Signing in with the password given to the setup didn't work.")
    version = call(url.rstrip("/") + "/api/version", token=token)
    print(f"the agent answers: version {version.get('version')}, API {version.get('api_version')}")

    program = Path(result.get("program_dir") or layout.default_program_dir())
    data_root = Path(result.get("data_root") or layout.data_root())
    leaks = [str(result_file)] if password in result_file.read_text("utf-8") else []
    if password in printed:
        leaks.append("the setup's output")
    for path in files_under(data_root) + files_under(program):
        try:
            if password.encode() in path.read_bytes():
                leaks.append(str(path))
        except OSError:
            pass
    if leaks:
        fail("The password was written to: " + ", ".join(leaks))
    print("the password is in no file or output")

    removed_file = work / "remove.json"
    done = subprocess.run(
        [
            str(program / layout.SETUP_COPY),
            "--uninstall",
            "--quiet",
            "--remove-data",
            "--result-file",
            str(removed_file),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(done.stdout + done.stderr)
    removed = json.loads(removed_file.read_text("utf-8")) if removed_file.is_file() else {}
    if done.returncode != 0 or not removed.get("ok"):
        fail(f"Removing the app failed: {removed or done.returncode}")
    # The program folder's own setup.exe goes once it has exited (a copy of
    # the setup removes it then): give that a moment.
    deadline = time.monotonic() + 60
    while program.exists() and time.monotonic() < deadline:
        time.sleep(1)
    left = [
        str(p)
        for p in (program, layout.start_menu_dir(), data_root)
        if p.exists() and any(p.iterdir())
    ]
    if left:
        fail("Still there after removing: " + ", ".join(left))
    from installer.autostart import TASK_NAME

    query = subprocess.run(["schtasks.exe", "/Query", "/TN", TASK_NAME], capture_output=True)
    if query.returncode == 0:
        fail(f"The startup task {TASK_NAME!r} is still registered.")
    print("removed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
