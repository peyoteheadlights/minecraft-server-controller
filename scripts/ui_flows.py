"""Interaction test for the dashboard, against the real agent.

Clicks the actual buttons in headless Chromium and checks what the page
shows at each step, including the loading and failure states.

Usage:  python scripts/ui_flows.py [screenshot_dir]
"""

import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ui_check import PASSWORD, start_agent  # noqa: E402

RESULTS = []


def step(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


def check(name, fn):
    try:
        detail = fn()
        step(name, True, detail or "")
    except Exception as exc:  # an assertion failure is a failed step, not a crash
        step(name, False, str(exc).splitlines()[0][:160])


def main():
    shots = Path(sys.argv[1] if len(sys.argv) > 1 else "ui-flows")
    shots.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="mcsc-flow-"))
    proc, base = start_agent(tmp)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            # Chrome logs every 4xx response as a console error. The one 401 this
            # script causes on purpose (the wrong password) is not a script error.
            page.on(
                "console",
                lambda m: (
                    m.type == "error" and "status of 401" not in m.text and errors.append(m.text)
                ),
            )
            title = page.locator("#server-state-title")
            actions = page.locator(".hero-actions")

            print("\n=== Sign in ===")
            page.goto(base + "/")
            check(
                "Wrong password shows a readable error",
                lambda: (
                    page.fill("#username", "admin"),
                    page.fill("#password", "wrong password"),
                    page.click("#login-form button[type=submit]"),
                    expect(page.locator("#login-error")).to_contain_text("not correct"),
                )[-1],
            )
            check(
                "Correct password opens Overview",
                lambda: (
                    page.fill("#password", PASSWORD),
                    page.click("#login-form button[type=submit]"),
                    expect(page.locator("#page-title")).to_have_text("Overview"),
                )[-1],
            )
            check(
                "Password field is cleared after sign-in",
                lambda: expect(page.locator("#password")).to_have_value(""),
            )

            print("\n=== Stopped server ===")
            check("Hero says Offline", lambda: expect(title).to_have_text("Offline"))
            check(
                "Only Start is offered, as the primary action",
                lambda: (
                    expect(actions.locator("button")).to_have_count(1),
                    expect(actions.locator("button.primary")).to_have_text("Start Server"),
                )[-1],
            )
            check(
                "Players shows a verified 0 (server not running), not a guess",
                lambda: expect(page.locator(".stat").first).to_contain_text("0"),
            )
            page.screenshot(path=str(shots / "01-offline.png"))

            print("\n=== Starting ===")
            start = actions.locator("button.primary")
            start.click()
            check(
                "Start button switches to a busy 'Starting…' state",
                lambda: expect(actions.locator("button")).to_contain_text("Starting"),
            )
            check(
                "Controls are disabled while starting",
                lambda: expect(actions.locator("button").first).to_be_disabled(),
            )
            check("Hero shows Starting…", lambda: expect(title).to_have_text("Starting…"))
            page.screenshot(path=str(shots / "02-starting.png"))
            check(
                "A second click cannot start twice",
                lambda: (
                    actions.locator("button").first.click(force=True, timeout=1000)
                    if actions.locator("button").first.is_enabled()
                    else None,
                    "button stayed disabled",
                )[-1],
            )
            check(
                "Server reaches Online", lambda: expect(title).to_have_text("Online", timeout=20000)
            )
            check(
                "Stop (destructive) and Restart are offered",
                lambda: (
                    expect(actions.locator("button.danger")).to_have_text("Stop Server"),
                    expect(actions.locator("button", has_text="Restart")).to_be_visible(),
                )[-1],
            )
            check(
                "Versions detected from the console appear",
                lambda: expect(page.locator("#server-state-detail")).to_contain_text(
                    "Minecraft 1.21.1"
                ),
            )
            events = httpx.get(
                f"{base}/api/events?limit=50",
                headers={
                    "Authorization": "Bearer "
                    + page.evaluate("sessionStorage.getItem('mcsc_token')")
                },
            ).json()
            starts = [e for e in events["events"] if e["type"] == "server_start_requested"]
            step(
                "Exactly one start request reached the agent",
                len(starts) == 1,
                f"{len(starts)} requests",
            )
            check(
                "Uptime counts up live",
                lambda: (
                    time.sleep(2.2),
                    expect(page.locator("#server-state-detail")).to_contain_text("Up for"),
                )[-1],
            )
            page.screenshot(path=str(shots / "03-online.png"))

            print("\n=== Live updates ===")
            token = page.evaluate("sessionStorage.getItem('mcsc_token')")
            auth = {"Authorization": f"Bearer {token}"}
            httpx.post(
                f"{base}/api/server/command", headers=auth, json={"command": "fakejoin Steve"}
            )
            check(
                "A player join appears without reloading",
                lambda: expect(page.locator(".row", has_text="Steve")).to_be_visible(timeout=5000),
            )
            check(
                "Console line streams into Recent console",
                lambda: expect(page.locator(".console-preview")).to_contain_text(
                    "Steve joined the game", timeout=5000
                ),
            )

            print("\n=== Stop, with confirmation ===")
            actions.locator("button.danger").click()
            dialog = page.locator("[role=dialog]")
            check(
                "Stop asks for confirmation",
                lambda: expect(dialog).to_contain_text("Players will be disconnected"),
            )
            check(
                "Focus starts on Cancel for a destructive action",
                lambda: expect(dialog.locator("button", has_text="Cancel")).to_be_focused(),
            )
            page.screenshot(path=str(shots / "04-stop-dialog.png"))
            page.keyboard.press("Escape")
            check(
                "Escape cancels and the server keeps running",
                lambda: (expect(dialog).to_have_count(0), expect(title).to_have_text("Online"))[-1],
            )
            actions.locator("button.danger").click()
            dialog.locator("button.danger-filled").click()
            check(
                "Stopping shows a busy state",
                lambda: expect(title).to_have_text("Stopping…", timeout=3000),
            )
            check(
                "Server ends Offline", lambda: expect(title).to_have_text("Offline", timeout=20000)
            )
            check(
                "Exactly one confirmation toast is shown",
                lambda: expect(page.locator(".toast", has_text="stopped")).to_have_count(
                    1, timeout=5000
                ),
            )

            print("\n=== Restart ===")
            actions.locator("button.primary").click()
            expect(title).to_have_text("Online", timeout=20000)
            actions.locator("button", has_text="Restart").click()
            dialog.locator("button.primary", has_text="Restart").click()
            # wait for the restart to actually begin, or "Online" would match at once
            check(
                "Restart shows it is in progress",
                lambda: expect(title).not_to_have_text("Online", timeout=10000),
            )
            check(
                "Restart comes back Online",
                lambda: expect(title).to_have_text("Online", timeout=30000),
            )

            print("\n=== Crash ===")
            httpx.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            check("Hero says Crashed", lambda: expect(title).to_have_text("Crashed", timeout=10000))
            check(
                "Explains in plain language, with the exit code",
                lambda: expect(page.locator("#server-state-detail")).to_contain_text(
                    "stopped unexpectedly"
                ),
            )
            check(
                "Shows this crash's exit code (1), not the previous stop's (0)",
                lambda: expect(page.locator("#server-state-detail")).to_contain_text(
                    "Exit code 1."
                ),
            )
            check(
                "States the cause from the crash report, with its confidence",
                lambda: expect(page.locator("#server-state-detail")).to_contain_text(
                    "Cause: the server ran out of memory", timeout=5000
                ),
            )
            check(
                "Offers crash details",
                lambda: expect(
                    actions.locator("button", has_text="View Crash Details")
                ).to_be_visible(),
            )
            check(
                "A toast offers the details too",
                lambda: expect(
                    page.locator(".toast", has_text="stopped unexpectedly")
                ).to_be_visible(timeout=5000),
            )
            page.screenshot(path=str(shots / "05-crashed.png"))
            check(
                "Automatic restart brings it back Online",
                lambda: expect(title).to_have_text("Online", timeout=30000),
            )

            print("\n=== Automatic restart countdown ===")
            httpx.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            countdown = page.locator(".countdown")
            check(
                "A crash starts a visible countdown",
                lambda: expect(countdown).to_contain_text("Restarting in", timeout=10000),
            )
            check(
                "Start Server is not offered during the countdown",
                lambda: expect(actions.locator("button", has_text="Start Server")).to_have_count(0),
            )
            check(
                "Restart Now and Cancel are offered",
                lambda: (
                    expect(actions.locator("button", has_text="Restart Now")).to_be_visible(),
                    expect(actions.locator("button", has_text="Cancel")).to_be_visible(),
                )[-1],
            )
            import re as _re

            first = int(_re.search(r"(\d+)s", countdown.inner_text()).group(1))
            page.wait_for_timeout(2100)
            later = int(_re.search(r"(\d+)s", countdown.inner_text()).group(1))
            step("The countdown ticks down", later < first, f"{first}s then {later}s")
            page.screenshot(path=str(shots / "05b-countdown.png"))
            code = httpx.post(f"{base}/api/server/start", headers=auth).status_code
            step(
                "The server refuses a normal start during the countdown (409)",
                code == 409,
                f"HTTP {code}",
            )
            actions.locator("button", has_text="Cancel").click()
            check(
                "Cancel says the restart was cancelled",
                lambda: expect(
                    page.locator(".toast", has_text="Automatic restart cancelled")
                ).to_be_visible(timeout=5000),
            )
            check(
                "After Cancel the server stays stopped and Start is offered again",
                lambda: (
                    expect(title).to_have_text("Crashed"),
                    expect(page.locator("#server-state-detail")).to_contain_text(
                        "Automatic restart cancelled"
                    ),
                    expect(actions.locator("button", has_text="Start Server")).to_be_visible(),
                )[-1],
            )
            page.wait_for_timeout(6000)  # past the original 5 s deadline
            check(
                "A cancelled restart does not fire later",
                lambda: expect(title).to_have_text("Crashed"),
            )
            actions.locator("button", has_text="Start Server").click()
            expect(title).to_have_text("Online", timeout=30000)
            httpx.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            expect(countdown).to_contain_text("Restarting in", timeout=10000)
            actions.locator("button", has_text="Restart Now").click()
            check(
                "Restart Now starts the server immediately",
                lambda: expect(title).to_have_text("Online", timeout=20000),
            )

            print("\n=== TPS monitoring ===")
            page.locator(".nav-item", has_text="Performance").click()
            panel = page.locator(".section", has_text="TPS monitoring")
            check(
                "The TPS panel shows detection is active",
                lambda: expect(panel).to_contain_text("Active", timeout=15000),
            )
            check(
                "It names the command in use", lambda: expect(panel).to_contain_text("tick query")
            )
            check(
                "It says the command was detected automatically",
                lambda: expect(panel).to_contain_text("Automatic"),
            )
            page.screenshot(path=str(shots / "05c-tps.png"))
            page.locator(".nav-item", has_text="Overview").click()
            check(
                "Overview names the TPS source",
                lambda: expect(page.locator(".stat", has_text="TPS")).to_contain_text(
                    "via tick query", timeout=10000
                ),
            )

            print("\n=== Dependencies ===")
            actions.locator("button.danger").click()
            page.locator("[role=dialog] button.danger-filled").click()
            expect(title).to_have_text("Offline", timeout=20000)
            page.locator(".nav-item", has_text="Mods").click()
            deps = page.locator(".section", has_text="Dependencies")
            check(
                "A missing dependency is shown in plain language",
                lambda: (
                    expect(deps).to_contain_text("Missing dependency", timeout=15000),
                    expect(deps).to_contain_text("Cloud"),
                    expect(deps).to_contain_text("Required by SkinsRestorer"),
                    expect(deps).to_contain_text("Version: Any version"),
                )[-1],
            )
            check(
                "The cryptic form is gone",
                lambda: expect(page.locator("#page")).not_to_contain_text("cloud *"),
            )
            check(
                "Install Missing Dependencies is offered",
                lambda: expect(
                    deps.locator("button", has_text="Install Missing Dependencies")
                ).to_be_enabled(),
            )
            page.screenshot(path=str(shots / "05d-dependencies.png"))
            page.locator(".nav-item", has_text="Overview").click()
            actions.locator("button.primary").click()
            expect(title).to_have_text("Online", timeout=30000)

            print("\n=== Console ===")
            page.locator(".nav-item", has_text="Console").click()
            check(
                "Console lists lines",
                lambda: expect(page.locator("#console-wrap .log-line").first).to_be_visible(),
            )
            page.fill("input[aria-label='Filter console lines']", "Steve")
            check(
                "Filter narrows the lines",
                lambda: (
                    expect(page.locator("#console-wrap .log-line").first).to_contain_text("Steve"),
                    f"{page.locator('#console-wrap .log-line').count()} matching lines",
                )[-1],
            )
            page.fill("input[aria-label='Filter console lines']", "zzz-nothing")
            check(
                "A filter with no matches shows an empty state",
                lambda: expect(page.locator("#console-wrap")).to_contain_text("No matching lines"),
            )
            page.fill("input[aria-label='Filter console lines']", "")
            follow = page.locator("button", has_text="Auto-scroll")
            follow.click()
            check(
                "Auto-scroll toggles off",
                lambda: expect(follow).to_have_attribute("aria-pressed", "false"),
            )
            follow.click()
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            page.locator("button", has_text="Copy").click()
            check(
                "Copy puts the lines on the clipboard",
                lambda: expect(page.locator(".toast", has_text="Copied")).to_be_visible(),
            )
            page.fill("input[aria-label='Minecraft command']", "op Steve")
            page.keyboard.press("Enter")
            check(
                "A dangerous command asks first", lambda: expect(dialog).to_contain_text("operator")
            )
            dialog.locator("button", has_text="Cancel").click()
            page.fill("input[aria-label='Minecraft command']", "say hello; shutdown")
            page.keyboard.press("Enter")
            check(
                "An invalid command is refused with a readable reason",
                lambda: expect(page.locator(".toast", has_text="not allowed")).to_be_visible(),
            )
            page.locator("button", has_text="Clear").click()
            check(
                "Clear empties the view",
                lambda: expect(page.locator("#console-wrap")).to_contain_text(
                    "No console output yet"
                ),
            )
            page.screenshot(path=str(shots / "06-console.png"))

            print("\n=== Appearance ===")
            page.locator("button[aria-label='Dark appearance']").click()
            check(
                "Dark appearance applies",
                lambda: expect(page.locator("html")).to_have_attribute("data-theme", "dark"),
            )
            page.reload()
            check(
                "Choice survives a reload",
                lambda: expect(page.locator("html")).to_have_attribute("data-theme", "dark"),
            )
            page.locator(".nav-item", has_text="Overview").click()
            expect(title).to_have_text("Online", timeout=10000)
            page.screenshot(path=str(shots / "07-dark-online.png"))
            page.locator("button[aria-label='Match system appearance']").click()
            check(
                "Match system removes the override",
                lambda: expect(page.locator("html")).not_to_have_attribute("data-theme", "dark"),
            )

            print("\n=== Keyboard and small screens ===")
            page.keyboard.press("Tab")
            check(
                "Keyboard focus is visible",
                lambda: (
                    page.evaluate("getComputedStyle(document.activeElement).boxShadow") != "none"
                    or page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
                    != "none"
                ),
            )
            page.set_viewport_size({"width": 390, "height": 844})
            check(
                "Menu button appears on a phone",
                lambda: expect(page.locator("#menu-button")).to_be_visible(),
            )
            page.locator("#menu-button").click()
            check(
                "Sections open as a drawer",
                lambda: expect(page.locator("#app")).to_have_class("app visible nav-open"),
            )
            page.screenshot(path=str(shots / "08-phone-menu.png"))
            page.locator(".nav-item", has_text="Players").click()
            check(
                "Choosing a section closes the drawer and navigates",
                lambda: (
                    expect(page.locator("#app")).not_to_have_class("app visible nav-open"),
                    expect(page.locator("#page-title")).to_have_text("Players"),
                )[-1],
            )
            page.set_viewport_size({"width": 1440, "height": 900})
            check(
                "Menu button hidden on desktop",
                lambda: expect(page.locator("#menu-button")).to_be_hidden(),
            )

            print("\n=== Sign out ===")
            page.locator(".signout").click()
            check(
                "Signing out returns to the sign-in screen",
                lambda: expect(page.locator("#login-form")).to_be_visible(),
            )
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()

    step("No JavaScript errors during the whole run", not errors, "; ".join(errors[:3]))

    passed = sum(ok for _, ok in RESULTS)
    print(f"\nUI FLOWS: {passed}/{len(RESULTS)} passed. Screenshots in {shots}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
