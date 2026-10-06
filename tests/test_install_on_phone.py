"""Phase 5: installing the dashboard on a phone.

The manifest, the icons and the service worker. The point that matters most
is the last test here: the service worker must never keep a copy of an API
answer, because a phone's cache is the one place this app's data could end
up outside the PC.
"""

import json
import re
import struct
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "agent" / "web"
SW = (WEB / "sw.js").read_text(encoding="utf-8")


def png_size(path):
    """(width, height) from a PNG's IHDR, without an image library."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


# ---------------------------------------------------------------- manifest
def test_the_manifest_says_what_a_phone_needs_to_install_it():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] and manifest["short_name"]
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"].startswith("#")
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    # Android crops a round icon out of this one, so it needs the full-bleed
    # artwork rather than the same square.
    assert any("maskable" in (icon.get("purpose") or "") for icon in manifest["icons"])


def test_every_icon_the_manifest_names_is_there_and_the_size_it_claims():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        path = WEB / icon["src"].lstrip("/").replace("assets/", "", 1)
        assert path.is_file(), icon["src"]
        if path.suffix == ".png":
            width, height = png_size(path)
            assert f"{width}x{height}" == icon["sizes"], path.name


def test_the_page_points_at_the_manifest_and_the_home_screen_icon():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'rel="manifest"' in html
    assert "manifest.webmanifest" in html
    # iPhones ignore the manifest's icons and use this one.
    assert 'rel="apple-touch-icon"' in html
    assert "apple-mobile-web-app-title" in html


def test_the_agent_serves_the_manifest_and_the_worker_from_the_root(client):
    from .conftest import PASSWORD

    # Both are served before sign-in: a phone fetches them while the
    # dashboard is still showing the sign-in page.
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert json.loads(manifest.text)["start_url"] == "/"

    worker = client.get("/sw.js")
    assert worker.status_code == 200
    # Served from the root, so it covers every page of the dashboard.
    assert worker.headers.get("service-worker-allowed") == "/"
    assert "no-cache" in worker.headers.get("cache-control", "")
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
        == 200
    )


def test_the_rules_allow_a_worker_and_a_manifest_and_nothing_else_new(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    assert "worker-src 'self'" in policy
    assert "manifest-src 'self'" in policy
    # The things the CSP has always refused are still refused.
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy
    assert "default-src 'self'" in policy


# ---------------------------------------------------------- service worker
def test_the_service_worker_never_keeps_a_copy_of_an_api_answer():
    """A phone must not end up holding player names, worlds or a token."""
    assert '"/api"' in SW or "'/api'" in SW
    guard = re.search(r"function isShellRequest\(url\) \{(.+?)\n\}", SW, re.S)
    assert guard, "the shell guard is what keeps /api out of the cache"
    body = guard.group(1)
    assert "/api" in body and "/ws" in body
    assert "return false" in body

    # Every cache write happens inside the branch the guard protects, and
    # the guard returns before any of them.
    before_guard, _, after_guard = SW.partition("function isShellRequest")
    assert "cache.put" not in before_guard
    assert "if (!isShellRequest(url)) return;" in after_guard


def test_the_service_worker_only_caches_this_app_s_own_files():
    assert "url.origin !== self.location.origin" in SW
    files = re.search(r"const SHELL_FILES = \[(.+?)\];", SW, re.S).group(1)
    for entry in re.findall(r'"([^"]+)"', files):
        assert entry.startswith("/"), entry
        assert not entry.startswith("/api"), entry
        if entry != "/":
            local = WEB / entry.lstrip("/").replace("assets/", "", 1)
            assert local.is_file(), entry


def test_the_service_worker_asks_the_network_first():
    """The cache is a fallback for a phone with no signal, never the first
    answer, so the dashboard is never a stale copy of itself."""
    fetch_handler = SW.partition('addEventListener("fetch"')[2]
    assert fetch_handler.index("fetch(request)") < fetch_handler.index("caches.match")


def test_a_phone_alert_shows_only_what_the_agent_sent():
    """Nothing is fetched while showing an alert, so it reads the same with
    or without a signal, and shows no value the agent did not send."""
    push_handler = SW.partition('addEventListener("push"')[2].partition("addEventListener(")[0]
    assert "fetch(" not in push_handler
    assert "showNotification" in push_handler


def test_the_worker_runs_no_code_it_was_sent():
    for forbidden in ("eval(", "new Function(", "importScripts("):
        assert forbidden not in SW


def test_registering_the_worker_is_the_only_place_it_is_named():
    pwa = (WEB / "js" / "pwa.js").read_text(encoding="utf-8")
    assert 'SW_URL = "/sw.js"' in pwa
    # A browser without service workers (an older iPhone) still gets a
    # working dashboard: everything here is behind a support check.
    assert "serviceWorker" in pwa and "function supported()" in pwa


def test_every_learn_more_link_opens_a_real_doc():
    """A "?" button's "Learn more" opens docs/<name>.md on GitHub, so each
    name passed to it has to be a file in docs/."""
    docs = WEB.parent.parent / "docs"
    ui = (WEB / "js" / "ui.js").read_text(encoding="utf-8")
    assert "${doc}.md" in ui
    used = set()
    for page in (WEB / "js").rglob("*.js"):
        text = page.read_text(encoding="utf-8")
        used |= set(re.findall(r'withHelp\([^;]*?"[a-z_]+", "([a-z-]+)"\)', text, re.S))
    assert used, "no help buttons found"
    for name in used:
        assert (docs / f"{name}.md").is_file(), name
