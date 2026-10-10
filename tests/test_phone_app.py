"""Phase 9: what the agent does for the phone app (mobile/). The app's own
pairing and requests are tested in mobile/android/core and mobile/ios/Core;
these cover the agent side: the alert list the app reads, who sees which
alert, and that signing out on the PC locks the app out."""

import asyncio
import logging
from pathlib import Path

import pytest

from agent.events import Event
from agent.notifications import dispatcher

from .test_helpers import add_helper

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def owner(multi_client):
    return dict(multi_client.headers)


def alerts_on(client, on=True):
    core = client.app.state.core
    response = client.put("/api/settings", json={"updates": {"notifications.push_enabled": on}})
    assert response.status_code == 200, response.text
    assert core.config.notifications.push_enabled is on
    return core


def send(core, event):
    async def go():
        await core.notifier.deliver(event)

    asyncio.run(go())


def crash(server_id="survival"):
    return Event(type="server_crashed", level="error", message="It crashed", server_id=server_id)


def test_an_alert_is_kept_for_the_app(multi_client):
    core = alerts_on(multi_client)
    start = multi_client.get("/api/alerts").json()
    assert start["alerts"] == [] and start["enabled"] is True
    send(core, crash())
    result = multi_client.get("/api/alerts", params={"after": start["latest"]}).json()
    [alert] = result["alerts"]
    assert alert["title"].endswith("Survival crashed")
    assert alert["server_id"] == "survival"
    # Tapping it opens that server's crash page, as Web Push alerts do.
    assert alert["url"] == "/#survival/crashes"
    assert result["latest"] == alert["id"]
    # Asked again from there, nothing repeats.
    again = multi_client.get("/api/alerts", params={"after": result["latest"]}).json()
    assert again["alerts"] == []


def test_alerts_are_kept_for_the_app_even_with_every_channel_off(multi_client):
    core = alerts_on(multi_client, False)
    send(core, crash())
    assert len(core.db.query("SELECT * FROM app_alerts")) == 1
    assert multi_client.get("/api/alerts").json()["enabled"] is False


def test_an_event_switched_off_in_alert_settings_isnt_kept(multi_client):
    core = alerts_on(multi_client)
    response = multi_client.put(
        "/api/settings", json={"updates": {"notifications.events.server_crashed": False}}
    )
    assert response.status_code == 200, response.text
    asyncio.run(core.notifier.handle(crash()))
    asyncio.run(core.notifier.drain())
    assert core.db.query("SELECT * FROM app_alerts") == []


def test_a_new_phone_doesnt_replay_old_alerts(multi_client):
    core = alerts_on(multi_client)
    send(core, crash())
    first = multi_client.get("/api/alerts").json()
    assert first["alerts"] == [] and first["latest"] > 0


def test_a_helper_sees_only_their_servers_alerts(multi_client, owner):
    core = alerts_on(multi_client)
    helper = add_helper(multi_client, owner, servers=["creative"])
    send(core, crash("survival"))
    send(core, crash("creative"))
    send(core, Event(type="auth_failure", level="warn", message="Wrong password"))
    multi_client.headers.pop("Authorization")
    seen = multi_client.get("/api/alerts", params={"after": 0}, headers=helper).json()
    assert [a["server_id"] for a in seen["alerts"]] == ["creative"]
    everything = multi_client.get("/api/alerts", params={"after": 0}, headers=owner).json()
    # (adding the helper sent its own alert about the PC first)
    shown = [(a["event"], a["server_id"]) for a in everything["alerts"]]
    assert shown[-3:] == [
        ("server_crashed", "survival"),
        ("server_crashed", "creative"),
        ("auth_failure", None),
    ]


def test_only_the_newest_alerts_are_kept(multi_client, monkeypatch):
    core = alerts_on(multi_client)
    monkeypatch.setattr(dispatcher, "APP_ALERTS_KEPT", 3)
    for _ in range(6):
        send(core, Event(type="backup_completed", level="success", server_id="survival"))
    assert [r["id"] for r in core.db.query("SELECT id FROM app_alerts")] == [4, 5, 6]


def test_a_long_list_comes_in_pages(multi_client):
    core = alerts_on(multi_client)
    for _ in range(5):
        send(core, Event(type="backup_completed", level="success", server_id="survival"))
    page = multi_client.get("/api/alerts", params={"after": 0, "limit": 2}).json()
    assert len(page["alerts"]) == 2
    assert page["more"] is True
    rest = multi_client.get("/api/alerts", params={"after": page["latest"], "limit": 50}).json()
    assert len(rest["alerts"]) == 3
    assert rest["more"] is False


def test_the_test_alert_reaches_the_app(multi_client):
    core = alerts_on(multi_client)
    result = multi_client.post("/api/push/test").json()
    assert result["for_app"] is True
    [row] = core.db.query("SELECT title FROM app_alerts")
    assert row["title"] == dispatcher.PUSH_TEST_TITLE


def test_signing_the_phone_out_on_the_pc_locks_the_app(multi_client, owner):
    phone = multi_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct horse battery", "device": "Android app"},
    ).json()
    headers = {"Authorization": f"Bearer {phone['token']}"}
    assert multi_client.get("/api/servers", headers=headers).status_code == 200
    sessions = multi_client.get("/api/sessions", headers=owner).json()["sessions"]
    [entry] = [s for s in sessions if s["label"] == "Android app"]
    assert multi_client.delete(f"/api/sessions/{entry['id']}", headers=owner).status_code == 200
    # What the app and its widget ask for next is refused: the app then
    # forgets the token (mobile/android/core AgentClientTest covers that side).
    for path in ("/api/servers", "/api/alerts", "/api/auth/me"):
        assert multi_client.get(path, headers=headers).status_code == 401


def test_the_app_shows_unknown_players_until_measured(multi_client):
    """The widget shows what /api/servers says: a player count is either
    measured or null (Unknown), never a guess."""
    rows = multi_client.get("/api/servers").json()["servers"]
    assert rows
    for row in rows:
        if row["state"] == "UNKNOWN":
            assert row["players_online"] is None
        if row["players_online"] is not None and row["state"] != "OFFLINE":
            assert row["players_verified"] is True


def test_no_token_reaches_the_log(multi_client, caplog):
    caplog.set_level(logging.DEBUG)
    phone = multi_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct horse battery"}
    ).json()
    multi_client.get("/api/alerts", headers={"Authorization": f"Bearer {phone['token']}"})
    assert phone["token"] not in caplog.text
    assert "correct horse battery" not in caplog.text


def test_every_route_the_app_uses_exists_and_is_typed():
    """The agent stays backward-compatible with the app: every route listed
    in mobile/api-routes.txt must keep existing with a typed answer."""
    from .test_api_contract import routes

    current = routes()
    listed = (ROOT / "mobile" / "api-routes.txt").read_text(encoding="utf-8").splitlines()
    used = [line.strip() for line in listed if line.strip() and not line.startswith("#")]
    assert "GET /api/alerts" in used
    for name in used:
        assert name in current, f"the phone app uses {name}, which is gone"
        assert current[name].response_model is not None, name


# ------------------------------------------------ lock-screen alerts (FCM)
def service_account(tmp_path, **changes):
    import json

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    data = {
        "type": "service_account",
        "project_id": "my-project",
        "client_email": "alerts@my-project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
        **changes,
    }
    path = tmp_path / "downloaded-key.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, key


@pytest.fixture
def google(multi_client, tmp_path, monkeypatch):
    """A Firebase key on the PC, and Google's two addresses answered by a
    mock that records every request."""
    import httpx

    from agent.notifications import fcm
    from installer.setup_phone_alerts import install_key

    path, key = service_account(tmp_path)
    install_key(multi_client.app.state.core.config, path)
    calls = []
    answers = {"send": (200, {"name": "projects/my-project/messages/1"})}

    def handler(request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        status, body = answers["send"]
        return httpx.Response(status, json=body)

    monkeypatch.setattr(fcm, "TRANSPORT", httpx.MockTransport(handler))
    return {"calls": calls, "answers": answers, "key": key}


PHONE_TOKEN = "fcm-token-" + "a" * 40


def register_phone(client, headers=None, token=PHONE_TOKEN):
    response = client.put(
        "/api/app/phone",
        json={"token": token, "platform": "android", "label": "Pixel"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def sends(calls):
    return [c for c in calls if c.url.host == "fcm.googleapis.com"]


def test_a_registered_phone_is_woken_without_any_words(multi_client, google):
    import json

    state = register_phone(multi_client)
    assert state["configured"] is True and state["registered"] is True
    core = multi_client.app.state.core
    send(core, crash())
    [request] = sends(google["calls"])
    assert request.url.path == "/v1/projects/my-project/messages:send"
    assert request.headers["Authorization"] == "Bearer ya29.test"
    body = json.loads(request.content)
    message = body["message"]
    assert message["token"] == PHONE_TOKEN
    alert_id = core.db.query_one("SELECT MAX(id) AS id FROM app_alerts")["id"]
    assert message["data"] == {"kind": "alert", "alert": str(alert_id)}
    # Nothing about the server, the event or what happened reaches Google.
    text = request.content.decode()
    for secret in ("Survival", "survival", "crash", "It crashed"):
        assert secret not in text


def test_the_token_request_is_signed_with_the_key(multi_client, google):
    import base64
    import json
    from urllib.parse import parse_qs

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    register_phone(multi_client)
    send(multi_client.app.state.core, crash())
    [token_request] = [c for c in google["calls"] if c.url.host == "oauth2.googleapis.com"]
    form = parse_qs(token_request.content.decode())
    header, claims, signature = form["assertion"][0].split(".")

    def unb64(text):
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    google["key"].public_key().verify(
        unb64(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert json.loads(unb64(claims))["scope"].endswith("/auth/firebase.messaging")


def test_a_helpers_phone_is_only_woken_for_their_servers(multi_client, owner, google):
    helper = add_helper(multi_client, owner, servers=["creative"])
    multi_client.headers.pop("Authorization")
    register_phone(multi_client, headers=helper)
    core = multi_client.app.state.core
    google["calls"].clear()
    send(core, crash("survival"))
    send(core, Event(type="auth_failure", level="warn", message="Wrong password"))
    assert sends(google["calls"]) == []
    send(core, crash("creative"))
    assert len(sends(google["calls"])) == 1


@pytest.mark.parametrize("how", ["logout", "device", "revoke_all"])
def test_signing_out_forgets_the_phone(multi_client, owner, google, how):
    phone = multi_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct horse battery", "device": "Pixel"},
    ).json()
    headers = {"Authorization": f"Bearer {phone['token']}"}
    register_phone(multi_client, headers=headers)
    core = multi_client.app.state.core
    assert len(core.db.query("SELECT * FROM app_phones")) == 1
    if how == "logout":
        multi_client.post("/api/auth/logout", headers=headers)
    elif how == "device":
        sessions = multi_client.get("/api/sessions", headers=owner).json()["sessions"]
        [entry] = [s for s in sessions if s["label"] == "Pixel"]
        multi_client.delete(f"/api/sessions/{entry['id']}", headers=owner)
    else:
        core.auth.revoke_all()
    assert core.db.query("SELECT * FROM app_phones") == []
    google["calls"].clear()
    send(core, crash())
    assert sends(google["calls"]) == []


def test_removing_a_helper_forgets_their_phone(multi_client, owner, google):
    helper = add_helper(multi_client, owner)
    multi_client.headers.pop("Authorization")
    register_phone(multi_client, headers=helper)
    assert multi_client.delete("/api/accounts/sam", headers=owner).status_code == 200
    assert multi_client.app.state.core.db.query("SELECT * FROM app_phones") == []


def test_a_phone_google_says_is_gone_is_forgotten(multi_client, google):
    register_phone(multi_client)
    google["answers"]["send"] = (
        404,
        {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}},
    )
    core = multi_client.app.state.core
    send(core, crash())
    assert core.db.query("SELECT * FROM app_phones") == []


def test_a_failed_send_is_recorded_not_raised(multi_client, google):
    register_phone(multi_client)
    google["answers"]["send"] = (503, {"error": {"status": "UNAVAILABLE"}})
    core = multi_client.app.state.core
    send(core, crash())
    [row] = core.db.query("SELECT last_result FROM app_phones")
    assert "503" in row["last_result"]
    # The alert itself is still in the Notifications tab.
    assert core.db.query("SELECT * FROM app_alerts")


def test_without_a_key_nothing_is_sent(multi_client, monkeypatch):
    import httpx

    from agent.notifications import fcm

    calls = []
    monkeypatch.setattr(
        fcm, "TRANSPORT", httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    )
    state = register_phone(multi_client)
    assert state["configured"] is False and state["registered"] is True
    send(multi_client.app.state.core, crash())
    assert calls == []


def test_turning_alerts_off_in_the_app_forgets_the_phone(multi_client, google):
    register_phone(multi_client)
    state = multi_client.delete("/api/app/phone").json()
    assert state["registered"] is False
    assert multi_client.app.state.core.db.query("SELECT * FROM app_phones") == []


def test_a_key_file_naming_another_address_is_refused(tmp_path):
    from agent.notifications import fcm

    path, _ = service_account(tmp_path, token_uri="https://evil.example/token")
    with pytest.raises(fcm.FcmError, match="unexpected"):
        fcm.load_service_account(path)
    path, _ = service_account(tmp_path, type="authorized_user")
    with pytest.raises(fcm.FcmError, match="isn't a Firebase"):
        fcm.load_service_account(path)


def test_the_key_is_copied_into_the_data_folder(config, tmp_path):
    from agent.notifications import fcm
    from installer.setup_phone_alerts import install_key

    path, _ = service_account(tmp_path)
    target = install_key(config, path)
    assert target == fcm.key_path(config)
    assert target.read_bytes() == path.read_bytes()
    assert str(target).startswith(str(config.data_dir))
    assert fcm.configured(config)


def test_a_bad_push_address_is_refused(multi_client):
    response = multi_client.put(
        "/api/app/phone", json={"token": "x y", "platform": "android", "label": ""}
    )
    assert response.status_code == 422


# ------------------------------------------------------------ the apps' files
def test_android_names_match_the_shared_words():
    """Android shows these few words before the app runs, from its own
    resources; they must say what mobile/shared/strings.json says."""
    import json
    import re

    strings = json.loads((ROOT / "mobile" / "shared" / "strings.json").read_text(encoding="utf-8"))
    xml = (ROOT / "mobile/android/app/src/main/res/values/strings.xml").read_text(encoding="utf-8")
    found = {
        name: text.replace("\\'", "'")
        for name, text in re.findall(r'<string name="([a-z_]+)">([^<]*)</string>', xml)
    }
    assert found == {
        "app_name": strings["mobile.app_name"][0],
        "widget_name": strings["mobile.widget.name"][0],
        "widget_description": strings["mobile.widget.description"][0],
    }


def test_every_library_in_the_android_app_is_in_its_licenses_list():
    import json
    import re
    import tomllib

    android = ROOT / "mobile" / "android"
    catalog = tomllib.loads((android / "gradle" / "libs.versions.toml").read_text(encoding="utf-8"))
    modules = {
        alias.replace("-", "."): spec["module"] for alias, spec in catalog["libraries"].items()
    }
    used = set()
    for module in ("app", "core"):
        build = (android / module / "build.gradle.kts").read_text(encoding="utf-8")
        for alias in re.findall(
            r"^\s*(?:implementation|api)\((?:platform\()?libs\.([\w.]+)", build, re.M
        ):
            used.add(modules[alias])
    assert len(used) > 15
    listed = json.loads(
        (android / "app" / "src" / "main" / "assets" / "licenses.json").read_text(encoding="utf-8")
    )
    groups = [entry["group"] for entry in listed]
    for module in used:
        group = module.split(":")[0]
        assert any(group == g or group.startswith(g + ".") for g in groups), module


def test_no_signing_keys_or_firebase_files_are_committed():
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for name in tracked:
        lowered = name.lower()
        assert not lowered.endswith((".jks", ".keystore", ".p12", ".mobileprovision")), name
        assert not lowered.endswith(("google-services.json", "googleservice-info.plist")), name


def test_the_apps_words_and_colors_are_up_to_date():
    """mobile/shared is generated from the dashboard's own files. After
    changing strings.js, feed.js, styles.css, colors.js or the palette, run:
    python mobile/tools/generate.py"""
    import shutil
    import subprocess
    import sys

    if shutil.which("node") is None:
        pytest.skip("needs Node to run the dashboard's colors.js")
    done = subprocess.run(
        [sys.executable, str(ROOT / "mobile" / "tools" / "generate.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_both_apps_carry_the_shared_version_and_name():
    import json

    import yaml

    version = json.loads((ROOT / "mobile" / "version.json").read_text(encoding="utf-8"))
    strings = json.loads((ROOT / "mobile" / "shared" / "strings.json").read_text(encoding="utf-8"))
    spec = yaml.safe_load((ROOT / "mobile" / "ios" / "project.yml").read_text(encoding="utf-8"))
    assert spec["settings"]["base"]["MARKETING_VERSION"] == version["app_version"]
    app = spec["targets"]["ServerController"]["info"]["properties"]
    assert app["CFBundleDisplayName"] == strings["mobile.app_name"][0]


def test_every_android_xml_file_is_well_formed():
    # Android's resource merger rejects what a browser forgives, such as "--"
    # inside a comment; CI's Android build would stop at the first one.
    import xml.etree.ElementTree as ET

    app = ROOT / "mobile" / "android" / "app" / "src" / "main"
    files = sorted(app.rglob("*.xml"))
    assert files
    for path in files:
        ET.parse(path)
