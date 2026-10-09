"""Interaction test for the dashboard, against the real agent.

Clicks the actual buttons in headless Chromium and checks what the page
shows at each step, including the loading and failure states.

Usage:  python scripts/ui_flows.py [screenshot_dir]
"""

import re
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ui_check import PASSWORD, chromium_path, start_agent  # noqa: E402

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
            browser = p.chromium.launch(executable_path=chromium_path())
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            # Chrome logs every 4xx response as a console error. The one 401 this
            # script causes on purpose (the wrong password) is not a script error,
            # and neither is the one 400 below.
            # The one 400 is the bad game setting saved on purpose below.
            allowed_400 = [1]
            # While the offline screen is tested, every API request is cut on
            # purpose, and Chrome logs each one.
            cutting = [False]

            def console_error(m):
                if m.type != "error" or "status of 401" in m.text:
                    return
                if cutting[0] and "ERR_FAILED" in m.text:
                    return
                if "status of 400" in m.text and allowed_400[0] > 0:
                    allowed_400[0] -= 1
                    return
                errors.append(m.text)

            page.on("console", console_error)
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
                    expect(page.locator("#login-error")).to_contain_text("isn't right"),
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
                    expect(actions.locator("button.primary")).to_have_text("Start"),
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
                    expect(actions.locator("button.danger")).to_have_text("Stop"),
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
                "Simple mode leaves the raw console off the Overview",
                lambda: expect(page.locator(".console-preview")).to_have_count(0),
            )

            print("\n=== Stop, with confirmation ===")
            actions.locator("button.danger").click()
            dialog = page.locator("[role=dialog]")
            check(
                "Stop asks for confirmation",
                lambda: expect(dialog).to_contain_text("Players are disconnected"),
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
                "Explains in plain language",
                lambda: expect(page.locator("#server-state-detail")).to_contain_text(
                    "The server crashed."
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
                    actions.locator("button", has_text="What happened?")
                ).to_be_visible(),
            )
            check(
                "A toast offers the details too",
                lambda: expect(page.locator(".toast", has_text="The server crashed")).to_be_visible(
                    timeout=5000
                ),
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
                "Start is not offered during the countdown",
                lambda: expect(
                    actions.get_by_role("button", name="Start", exact=True)
                ).to_have_count(0),
            )
            check(
                "Restart now and Cancel are offered",
                lambda: (
                    expect(actions.locator("button", has_text="Restart now")).to_be_visible(),
                    expect(actions.locator("button", has_text="Cancel")).to_be_visible(),
                )[-1],
            )
            import re as _re

            first = int(_re.search(r"(\d+)", countdown.inner_text()).group(1))
            page.wait_for_timeout(2100)
            later = int(_re.search(r"(\d+)", countdown.inner_text()).group(1))
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
                        "Auto restart cancelled"
                    ),
                    expect(actions.get_by_role("button", name="Start", exact=True)).to_be_visible(),
                )[-1],
            )
            page.wait_for_timeout(6000)  # past the original 5 s deadline
            check(
                "A cancelled restart does not fire later",
                lambda: expect(title).to_have_text("Crashed"),
            )
            actions.get_by_role("button", name="Start", exact=True).click()
            expect(title).to_have_text("Online", timeout=30000)
            httpx.post(f"{base}/api/server/command", headers=auth, json={"command": "crash"})
            expect(countdown).to_contain_text("Restarting in", timeout=10000)
            actions.locator("button", has_text="Restart now").click()
            check(
                "Restart now starts the server immediately",
                lambda: expect(title).to_have_text("Online", timeout=20000),
            )

            print("\n=== Simple and Technical ===")
            check(
                "Simple mode says server speed in everyday words",
                lambda: expect(page.locator(".stat").nth(1)).to_contain_text("Game speed"),
            )
            page.locator(".nav-item", has_text="Performance").click()
            page.locator("details.advanced > summary").first.click()
            page.get_by_role("button", name="Show technical details").first.click()
            check(
                "An Advanced section's link switches to Technical",
                lambda: expect(page.locator("html")).to_have_attribute("data-mode", "technical"),
            )
            page.locator("#gear").click()
            page.get_by_role("radio", name="Simple").check()
            expect(page.locator("html")).to_have_attribute("data-mode", "simple")
            page.get_by_role("radio", name="Technical").check()
            check(
                "Technical mode applies at once, without a reload",
                lambda: expect(page.locator("html")).to_have_attribute("data-mode", "technical"),
            )
            page.locator("#tab-ui").click()
            check(
                "Technical mode uses the precise term",
                lambda: expect(page.locator(".stat").nth(1)).to_contain_text("TPS"),
            )

            print("\n=== TPS monitoring ===")
            page.locator(".nav-item", has_text="Performance").click()
            panel = page.locator("details.advanced", has_text="TPS source")
            check(
                "The TPS panel is open in Technical mode and shows detection is active",
                lambda: expect(panel).to_contain_text("Active", timeout=15000),
            )
            check(
                "It names the command in use", lambda: expect(panel).to_contain_text("tick query")
            )
            check(
                "It says the command was detected automatically",
                lambda: expect(panel).to_contain_text(
                    re.compile(r"Auto-detected|Auto \(remembered\)")
                ),
            )
            check(
                "Graphs have value and time axes",
                lambda: expect(page.locator(".chart-box svg .tick.x").first).to_be_visible(),
            )
            page.screenshot(path=str(shots / "05c-tps.png"))
            page.locator(".nav-item", has_text="Overview").click()
            check(
                "Overview names the TPS source",
                lambda: expect(page.locator(".stat", has_text="TPS")).to_contain_text(
                    "via tick query", timeout=10000
                ),
            )
            httpx.post(
                f"{base}/api/server/command", headers=auth, json={"command": "fakejoin Alex"}
            )
            check(
                "Technical mode shows the console streaming on the Overview",
                lambda: expect(page.locator(".console-preview")).to_contain_text(
                    "Alex joined the game", timeout=5000
                ),
            )
            page.locator("#gear").click()
            page.get_by_role("radio", name="Simple").check()
            page.locator("#tab-ui").click()
            check(
                "Back in Simple mode the extra detail is folded away",
                lambda: expect(page.locator(".stat").nth(1)).to_contain_text("Game speed"),
            )

            print("\n=== Dependencies ===")
            actions.locator("button.danger").click()
            page.locator("[role=dialog] button.danger-filled").click()
            expect(title).to_have_text("Offline", timeout=20000)
            page.locator(".nav-item", has_text="Mods").click()
            deps = page.locator(".section", has_text="Required mods")
            check(
                "A missing dependency is shown in plain language",
                lambda: (
                    expect(deps).to_contain_text("needed mod is missing", timeout=15000),
                    expect(deps).to_contain_text("Cloud"),
                    expect(deps).to_contain_text("Needed by SkinsRestorer"),
                    expect(deps).to_contain_text("Version: Any version"),
                )[-1],
            )
            check(
                "The cryptic form is gone",
                lambda: expect(page.locator("#page")).not_to_contain_text("cloud *"),
            )
            check(
                "Install missing is offered",
                lambda: expect(deps.locator("button", has_text="Install missing")).to_be_enabled(),
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
            page.fill("input[aria-label='Show lines containing']", "Steve")
            check(
                "Filter narrows the lines",
                lambda: (
                    expect(page.locator("#console-wrap .log-line").first).to_contain_text("Steve"),
                    f"{page.locator('#console-wrap .log-line').count()} matching lines",
                )[-1],
            )
            page.fill("input[aria-label='Show lines containing']", "zzz-nothing")
            check(
                "A filter with no matches shows an empty state",
                lambda: expect(page.locator("#console-wrap")).to_contain_text("No matches"),
            )
            page.fill("input[aria-label='Show lines containing']", "")
            follow = page.locator("button", has_text="Follow")
            follow.click()
            check(
                "Follow toggles off",
                lambda: expect(follow).to_have_attribute("aria-pressed", "false"),
            )
            follow.click()
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            page.locator("button", has_text="Copy").click()
            check(
                "Copy puts the lines on the clipboard",
                lambda: expect(page.locator(".toast", has_text="Copied")).to_be_visible(),
            )
            page.fill("input[aria-label='Command']", "op Steve")
            page.keyboard.press("Enter")
            check(
                "A dangerous command asks first", lambda: expect(dialog).to_contain_text("operator")
            )
            dialog.locator("button", has_text="Cancel").click()
            page.fill("input[aria-label='Command']", "say hello; shutdown")
            page.keyboard.press("Enter")
            check(
                "An invalid command is refused with a readable reason",
                lambda: expect(page.locator(".toast", has_text="allowed")).to_be_visible(),
            )
            page.locator("button", has_text="Clear").click()
            check(
                "Clear empties the view",
                lambda: expect(page.locator("#console-wrap")).to_contain_text("Nothing here yet"),
            )
            page.screenshot(path=str(shots / "06-console.png"))

            print("\n=== Tabs and colors ===")
            survival_band = page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent-band')"
            )
            page.locator("#tab-creative").click()
            check(
                "A server's tab opens its own sheet",
                lambda: expect(page.locator("#sheet-name")).to_have_text("Creative"),
            )
            check(
                "Each server's sheet has its own color",
                lambda: (
                    page.evaluate(
                        "getComputedStyle(document.documentElement).getPropertyValue('--accent-band')"
                    )
                    != survival_band
                ),
            )
            page.locator("#tab-creative").focus()
            page.keyboard.press("ArrowLeft")
            check(
                "Arrow keys move between tabs",
                lambda: expect(page.locator("#sheet-name")).to_have_text("Survival"),
            )
            page.locator(".nav-item", has_text="Server settings").click()
            page.get_by_role("radio", name="Green").check()
            page.locator("button", has_text="Save name and color").click()
            check(
                "Picking a color recolors the tab",
                lambda: expect(page.locator("#tab-ui")).to_have_attribute(
                    "style", re.compile("--tab-fill"), timeout=5000
                ),
            )
            page.locator("#tab-all").click()
            check(
                "All servers shows a card per server",
                lambda: expect(page.locator(".server-card")).to_have_count(2),
            )
            page.screenshot(path=str(shots / "06b-all-servers.png"))

            print("\n=== Server types ===")
            page.locator("#tab-ui").click()
            page.locator(".nav-item", has_text="Server settings").click()
            check(
                "The settings page names the kind of server",
                lambda: expect(
                    page.locator(".section", has_text="Kind and version")
                ).to_be_visible(),
            )
            check(
                "The version shown is the one the console reported",
                lambda: expect(
                    page.locator(".row", has_text="Minecraft version").locator(".row-value")
                ).to_have_text("1.21.1"),
            )
            check(
                "Bedrock crossplay is offered, switched off",
                lambda: expect(
                    page.locator("button", has_text="Let Bedrock players join")
                ).to_be_visible(),
            )
            check(
                "The Bedrock differences are spelled out before anything is turned on",
                lambda: expect(page.locator(".plain-list li").first).to_contain_text("Bedrock"),
            )
            page.locator("#tab-add").click()
            check(
                "The + tab offers a new server, a modpack and a folder you already have",
                lambda: expect(page.locator(".add-ways button")).to_have_count(3),
            )
            check(
                "Every kind of server this app supports is in the table",
                lambda: expect(page.locator(".type-table tbody tr")).to_have_count(7),
            )
            check(
                "One kind is marked as the one to pick",
                lambda: expect(page.locator(".type-table .rec-tag")).to_have_count(1),
            )
            check(
                "Nothing is chosen for the person",
                lambda: expect(page.locator(".type-table .btn.primary")).to_have_count(0),
            )
            check(
                "Bedrock servers say they come later rather than being offered",
                lambda: expect(page.get_by_role("radio", name="Bedrock Edition")).to_be_disabled(),
            )
            page.screenshot(path=str(shots / "06c-new-server.png"))
            page.get_by_role("button", name="Server I already have").click()
            check(
                "The folder-I-already-have way is still there",
                lambda: expect(page.locator("#add-server-folder")).to_be_visible(),
            )

            page.get_by_role("button", name="From a modpack").click()
            check(
                "A modpack is read first: only a file picker until one is chosen",
                lambda: (
                    expect(page.locator("#pack-file-new")).to_be_visible(),
                    expect(page.locator("#pack-name")).to_have_count(0),
                )[-1],
            )

            print("\n=== Everyday features ===")
            page.locator("#tab-ui").click()
            page.locator(".nav-item", has_text="Game settings").click()
            check(
                "Game settings shows the known settings as a form",
                lambda: (
                    expect(page.locator("#game-difficulty")).to_be_visible(),
                    expect(page.locator("#game-max-players")).to_be_visible(),
                )[-1],
            )
            page.fill("#game-max-players", "0")
            page.locator("button", has_text="Save").first.click()
            check(
                "A bad value is marked on its field and nothing is saved",
                lambda: expect(page.locator("#game-max-players-error")).not_to_be_empty(),
            )
            page.fill("#game-max-players", "12")
            page.locator("button", has_text="Save").first.click()
            check(
                "A good value saves and says when it takes effect",
                lambda: expect(page.locator(".toast").last).to_contain_text("Saved"),
            )
            page.screenshot(path=str(shots / "09-game-settings.png"))
            page.locator(".nav-item", has_text="Players").click()
            check(
                "Players has an add-by-name card and Minecraft's own lists",
                lambda: (
                    expect(page.locator("#player-add-name")).to_be_visible(),
                    expect(page.locator(".section h2", has_text="Whitelist")).to_be_visible(),
                )[-1],
            )
            add = page.locator("button", has_text="Add to whitelist").first
            if add.is_enabled():
                page.fill("#player-add-name", "Alex")
                add.click()
                check(
                    "Whitelisting shows Sent, then Done once the console confirms",
                    lambda: expect(page.locator(".action-lines li").first).to_contain_text(
                        "Done", timeout=10000
                    ),
                )
            page.fill("#player-add-name", "bad name!")
            check(
                "A name that isn't a Minecraft name is not sent",
                lambda: (
                    page.locator("button", has_text="Add to whitelist").first.click()
                    if page.locator("button", has_text="Add to whitelist").first.is_enabled()
                    else None,
                    expect(page.locator(".action-lines li", has_text="bad name")).to_have_count(0),
                )[-1],
            )
            page.screenshot(path=str(shots / "10-players.png"))
            page.locator(".nav-item", has_text="Overview").click()
            check(
                "Overview shows how friends join, with copy buttons",
                lambda: (
                    expect(page.locator(".join-card")).to_be_visible(),
                    expect(page.locator(".join-card")).to_contain_text("not known"),
                )[-1],
            )

            print("\n=== Appearance ===")
            page.locator("#gear").click()
            page.get_by_role("radio", name="Dark").check()
            check(
                "Dark appearance applies",
                lambda: expect(page.locator("html")).to_have_attribute("data-theme", "dark"),
            )
            page.reload()
            check(
                "Choice survives a reload",
                lambda: expect(page.locator("html")).to_have_attribute("data-theme", "dark"),
            )
            page.locator("#tab-ui").click()
            expect(title).to_have_text("Online", timeout=10000)
            page.screenshot(path=str(shots / "07-dark-online.png"))
            page.locator("#gear").click()
            page.get_by_role("radio", name="Match my device").check()
            check(
                "Match my device removes the override",
                lambda: expect(page.locator("html")).not_to_have_attribute("data-theme", "dark"),
            )

            print("\n=== Keyboard and small screens ===")
            page.locator("#tab-ui").click()
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
                "On a phone the tabs stay in one row that scrolls sideways",
                lambda: page.evaluate(
                    "(() => { const t = document.getElementById('server-tabs');"
                    " return getComputedStyle(t).overflowX === 'auto'"
                    " && document.documentElement.scrollWidth <= window.innerWidth; })()"
                ),
            )
            page.locator(".nav-item", has_text="Players").click()
            check(
                "The server's pages are reachable on a phone",
                lambda: expect(page.locator("#page-title")).to_have_text("Players"),
            )
            page.screenshot(path=str(shots / "08-phone.png"))
            page.set_viewport_size({"width": 1440, "height": 900})

            print("\n=== Helpers, Getting started, offline ===")
            page.evaluate("location.hash = 'helpers'")
            page.fill("#helper-name", "sam")
            page.fill("#helper-password", "helper password 1")
            page.locator("button", has_text="Add helper").click()
            check(
                "The owner adds a helper",
                lambda: expect(page.locator("table")).to_contain_text("sam", timeout=8000),
            )
            page.screenshot(path=str(shots / "11-helpers.png"))
            page.evaluate("location.hash = 'getting-started'")
            check(
                "Getting started lists the steps with buttons",
                lambda: expect(page.locator(".guide-step")).to_have_count(7),
            )
            cutting[0] = True
            page.route("**/api/**", lambda route: route.abort())
            page.evaluate("location.hash = 'backups'")
            check(
                "When the PC can't be reached, the offline screen shows",
                lambda: expect(page.locator("#offline")).to_be_visible(timeout=8000),
            )
            check(
                "It says it will try again by itself",
                lambda: expect(page.locator("#offline-next")).to_contain_text(
                    "Trying", timeout=8000
                ),
            )
            page.screenshot(path=str(shots / "12-offline.png"))
            page.unroute("**/api/**")
            page.locator("#offline button", has_text="Try now").click()
            check(
                "Once the PC answers, it goes away by itself",
                lambda: expect(page.locator("#offline")).to_be_hidden(timeout=15000),
            )
            page.wait_for_timeout(1000)
            cutting[0] = False

            print("\n=== Sign out ===")
            page.locator(".signout").click()
            check(
                "Signing out returns to the sign-in screen",
                lambda: expect(page.locator("#login-form")).to_be_visible(),
            )

            print("\n=== A helper's view ===")
            page.fill("#username", "sam")
            page.fill("#password", "helper password 1")
            page.click("#login-form button[type=submit]")
            page.wait_for_timeout(1500)
            check(
                "A helper has no add-server tab",
                lambda: expect(page.locator("#tab-add")).to_have_count(0),
            )
            page.evaluate("location.hash = 'backups'")
            check(
                "A helper can back up but sees no Delete or Restore",
                lambda: (
                    expect(page.locator("button", has_text="Back up now")).to_be_visible(),
                    expect(page.locator("button.danger", has_text="Delete")).to_have_count(0),
                )[-1],
            )
            page.locator("#gear").click()
            check(
                "A helper's settings have no Helpers or Security page",
                lambda: (
                    expect(page.locator(".nav-item", has_text="Helpers")).to_have_count(0),
                    expect(page.locator(".nav-item", has_text="Security")).to_have_count(0),
                    expect(page.locator(".section h2", has_text="Your account")).to_be_visible(),
                )[-1],
            )
            page.evaluate("location.hash = 'helpers'")
            check(
                "Typing the Helpers address sends a helper to the Overview",
                lambda: expect(page.locator("#page-title")).to_have_text("Overview"),
            )
            page.screenshot(path=str(shots / "13-helper.png"))
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
